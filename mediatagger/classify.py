"""Zero-shot scene gate and tagging with OpenCLIP-compatible models (BioCLIP, generic CLIP)."""
from __future__ import annotations

from dataclasses import dataclass

from .vocabulary import VocabEntry

MODELS = {
    "bioclip": "hf-hub:imageomics/bioclip",
    "clip": "hf-hub:laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
}

SCENE_PROMPTS = {
    "underwater": [
        "an underwater photo taken while scuba diving",
        "a photo of a coral reef underwater",
        "a photo of fish swimming in blue water",
    ],
    "topside": [
        "a photo of the sea surface with a boat",
        "an aerial drone photo of an island and the ocean",
        "a photo of a tropical beach at sunset",
    ],
    "land": [
        "a photo taken on land in a city street",
        "a photo of a forest or mountain landscape",
        "a photo of food or people indoors",
    ],
}

# Give the softmax somewhere to put its probability when no label really fits.
BACKGROUND_PROMPTS = [
    "a photo of nothing in particular",
    "a blurry photo",
    "a photo of people posing",
    "a close-up of a hand or an object",
]

SCENE_THRESHOLD = 0.2  # scenes at least this likely stay allowed for tagging


@dataclass
class Suggestion:
    keyword: str
    prob: float
    tier: str

    def as_dict(self) -> dict:
        return {"keyword": self.keyword, "prob": round(self.prob, 4), "tier": self.tier}


class Tagger:
    def __init__(self, model_key: str, device: str, vocabulary: list[VocabEntry]):
        import open_clip
        import torch

        name = MODELS[model_key]
        self.torch = torch
        self.model_key = model_key
        self.device = device
        self.vocab = vocabulary
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(name)
        self.tokenizer = open_clip.get_tokenizer(name)
        self.model.to(device).eval()
        self.scale = float(self.model.logit_scale.exp().detach())

        self.scene_names = list(SCENE_PROMPTS)
        self.scene_emb = torch.stack([self._mean_text(p) for p in SCENE_PROMPTS.values()])
        self.label_emb = self._encode_texts([self._label_text(e) for e in vocabulary])
        self.background_emb = self._encode_texts(BACKGROUND_PROMPTS)

    def _label_text(self, entry: VocabEntry) -> str:
        # BioCLIP was trained on taxonomic names, so prefer them when we have one.
        if self.model_key == "bioclip" and entry.scientific_name:
            return f"a photo of {entry.scientific_name}"
        return entry.prompt

    def _encode_texts(self, prompts: list[str]):
        with self.torch.inference_mode():
            tokens = self.tokenizer(prompts).to(self.device)
            emb = self.model.encode_text(tokens)
            return emb / emb.norm(dim=-1, keepdim=True)

    def _mean_text(self, prompts: list[str]):
        emb = self._encode_texts(prompts).mean(dim=0)
        return emb / emb.norm()

    def encode_images(self, images: list):
        with self.torch.inference_mode():
            batch = self.torch.stack([self.preprocess(im) for im in images]).to(self.device)
            emb = self.model.encode_image(batch)
            return emb / emb.norm(dim=-1, keepdim=True)

    def classify(self, image_emb, top: int = 5) -> dict:
        """Scene probabilities plus the top suggestions per tier, limited to the scene."""
        torch = self.torch
        scene_probs = (self.scale * self.scene_emb @ image_emb).softmax(dim=0)
        scenes = dict(zip(self.scene_names, scene_probs.tolist()))
        allowed = {s for s, p in scenes.items() if p >= SCENE_THRESHOLD} or {max(scenes, key=scenes.get)}

        suggestions: list[Suggestion] = []
        all_probs: dict[str, float] = {}
        for tier in sorted({e.tier for e in self.vocab}):
            idx = [i for i, e in enumerate(self.vocab) if e.tier == tier and e.scenes & allowed]
            if not idx:
                continue
            sims = torch.cat(
                [self.scale * self.label_emb[idx] @ image_emb,
                 self.scale * self.background_emb @ image_emb]
            )
            probs = sims.softmax(dim=0)[: len(idx)].tolist()
            all_probs.update((self.vocab[i].keyword, p) for i, p in zip(idx, probs))
            ranked = sorted(zip(idx, probs), key=lambda x: -x[1])[:top]
            suggestions += [Suggestion(self.vocab[i].keyword, p, tier) for i, p in ranked]
        return {"scene": scenes, "suggestions": suggestions, "all_probs": all_probs, "allowed": allowed}

    def conditional(self, image_emb, indices: list[int]) -> list[float]:
        """Probabilities among the given vocabulary rows plus 'something else' (background)."""
        sims = self.torch.cat(
            [self.scale * self.label_emb[indices] @ image_emb,
             self.scale * self.background_emb @ image_emb]
        )
        return sims.softmax(dim=0)[: len(indices)].tolist()


SPECIES_PARENT_GATE = 0.3  # a species is only judged when its parent group is this likely


class HybridTagger:
    """Generic CLIP for scene and groups; BioCLIP only for species inside a likely group."""

    def __init__(self, device: str, vocabulary: list[VocabEntry], gate: float = SPECIES_PARENT_GATE):
        core = [e for e in vocabulary if e.tier == "core"]
        species = [e for e in vocabulary if e.tier == "species"]
        self.gate = gate
        self.clip = Tagger("clip", device, core)
        self.bio = Tagger("bioclip", device, species) if species else None
        self.children: dict[str, list[int]] = {}
        core_keys = {e.keyword for e in core}
        for i, e in enumerate(species):
            parent = e.keyword.rsplit("|", 1)[0]
            if parent in core_keys:
                self.children.setdefault(parent, []).append(i)

    def encode_images(self, images: list):
        clip = self.clip.encode_images(images)
        bio = self.bio.encode_images(images) if self.bio else [None] * len(images)
        return list(zip(clip, bio))

    def classify(self, embeddings, top: int = 5) -> dict:
        clip_emb, bio_emb = embeddings
        result = self.clip.classify(clip_emb, top=top)
        if self.bio is None:
            return result
        allowed = result["allowed"]
        for parent, indices in self.children.items():
            parent_prob = result["all_probs"].get(parent, 0.0)
            if parent_prob < self.gate:
                continue
            indices = [i for i in indices if self.bio.vocab[i].scenes & allowed]
            if not indices:
                continue
            probs = self.bio.conditional(bio_emb, indices)
            ranked = sorted(zip(indices, probs), key=lambda x: -x[1])[:top]
            result["suggestions"] += [
                Suggestion(self.bio.vocab[i].keyword, parent_prob * p, "species") for i, p in ranked
            ]
        return result
