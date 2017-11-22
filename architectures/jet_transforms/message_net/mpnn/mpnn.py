import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from data_ops.batching import batch_leaves
from data_ops.batching import trees_as_adjacency_matrices

from ..readout import DTNNReadout, SetReadout

from ..message_passing import *


class MPNNTransform(nn.Module):
    def __init__(self,
        features=None,
        hidden=None,
        targets=None,
        iters=None,
        message_passing_layer=None,
        readout=None,
        **kwargs
        ):
        super().__init__()
        self.iters = iters
        self.activation = F.tanh
        self.hidden = hidden
        self.features = features + 1
        self.embedding = nn.Linear(self.features, hidden)
        if readout is None:
            self.readout = DTNNReadout(hidden, hidden)
        else:
            self.readout = readout
        self.multiple_iterations_of_message_passing = MultipleIterationMessagePassingLayer(iters, hidden, message_passing_layer)

    def forward(self, jets, return_extras=False, **kwargs):
        jets, mask = batch_leaves(jets)
        h = self.activation(self.embedding(jets))
        stuff = self.multiple_iterations_of_message_passing(h, mask, return_extras)
        if return_extras:
            h, A = stuff
        else:
            h = stuff
        out = self.readout(h)
        if return_extras:
            return out, A
        else:
            return out
