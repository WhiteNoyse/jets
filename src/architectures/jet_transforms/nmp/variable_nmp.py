import torch
import torch.nn as nn
import torch.nn.functional as F

from ....architectures.readout import construct_readout
from ....architectures.embedding import construct_embedding
from .message_passing import construct_mp_layer

class LearnedVariableNMP(nn.Module):
    def __init__(self,
        features=None,
        hidden=None,
        iters=None,
        mp_layer=None,
        readout=None,
        **kwargs
        ):
        super().__init__()
        self.iters = iters
        self.embedding = construct_embedding('simple', features + 1, hidden, act=kwargs.get('act', None))
        self.mp_layers = nn.ModuleList([construct_mp_layer(mp_layer,hidden=hidden,**kwargs) for _ in range(iters)])
        self.readout = construct_readout(readout, hidden, hidden)

    def forward(self, jets, mask=None, **kwargs):
        h = self.embedding(jets)
        for mp in self.mp_layers:
            h, A = mp(h=h, mask=mask, **kwargs)
        out = self.readout(h)
        return out, A