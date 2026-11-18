"""Collaborative models: LightFM (main CF model) and a small neural CF in PyTorch
(an offline baseline that the LightFM model is compared against)."""

from __future__ import annotations

import os

import numpy as np
import scipy.sparse as sp


def train_lightfm(pos: sp.csr_matrix, cfg: dict, seed: int = 42):
    from lightfm import LightFM  # only needed for training, not by the API

    model = LightFM(no_components=int(cfg["no_components"]), learning_rate=float(cfg["learning_rate"]),
                    item_alpha=float(cfg["item_alpha"]), loss=cfg.get("loss", "warp"), random_state=seed)
    model.fit(pos.tocoo(), epochs=int(cfg["epochs"]), num_threads=min(8, os.cpu_count() or 1))
    return model


def lightfm_arrays(model) -> dict:
    """Embeddings and biases, so serving needs only NumPy (no LightFM install)."""
    return {
        "item_emb": model.item_embeddings.astype(np.float32),
        "item_bias": model.item_biases.astype(np.float32),
        "user_emb": model.user_embeddings.astype(np.float32),
        "user_bias": model.user_biases.astype(np.float32),
    }


def train_ncf(pos: sp.csr_matrix, cfg: dict, seed: int = 42):
    """Neural CF (GMF and MLP towers, as in He et al. 2017) trained with a BPR loss on
    sampled negatives. Returns a function that scores a batch of users against all items."""
    import torch
    from torch import nn

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    n_users, n_items = pos.shape
    dim = int(cfg["dim"])

    class NCF(nn.Module):
        def __init__(self):
            super().__init__()
            self.ug, self.ig = nn.Embedding(n_users, dim), nn.Embedding(n_items, dim)
            self.um, self.im = nn.Embedding(n_users, dim), nn.Embedding(n_items, dim)
            self.mlp = nn.Sequential(nn.Linear(2 * dim, dim), nn.ReLU(), nn.Linear(dim, dim // 2), nn.ReLU())
            self.out = nn.Linear(dim + dim // 2, 1)
            for e in (self.ug, self.ig, self.um, self.im):
                nn.init.normal_(e.weight, std=0.05)

        def forward(self, u, i):
            g = self.ug(u) * self.ig(i)
            m = self.mlp(torch.cat([self.um(u), self.im(i)], dim=-1))
            return self.out(torch.cat([g, m], dim=-1)).squeeze(-1)

    model = NCF()
    opt = torch.optim.Adam(model.parameters(), lr=float(cfg["lr"]), weight_decay=1e-6)
    coo = pos.tocoo()
    users, items = coo.row.astype(np.int64), coo.col.astype(np.int64)
    bs = int(cfg["batch_size"])
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    for _ in range(int(cfg["epochs"])):
        perm = rng.permutation(len(users))
        for s in range(0, len(perm), bs):
            b = perm[s:s + bs]
            u = torch.from_numpy(users[b])
            i = torch.from_numpy(items[b])
            j = torch.from_numpy(rng.integers(0, n_items, len(b)))
            loss = -torch.nn.functional.logsigmoid(model(u, i) - model(u, j)).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    model.eval()

    def score(user_idx: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            out = []
            all_items = torch.arange(n_items)
            for u in user_idx:
                uu = torch.full((n_items,), int(u), dtype=torch.long)
                out.append(model(uu, all_items).numpy())
            return np.vstack(out).astype(np.float32)

    return score
