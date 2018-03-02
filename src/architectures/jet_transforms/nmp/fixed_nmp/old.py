
class FixedAdjacencyNMP(nn.Module):
    def __init__(self,
        features=None,
        hidden=None,
        iters=None,
        readout=None,
        matrix=None,
        **kwargs
        ):
        super().__init__()
        self.iters = iters
        self.embedding = construct_embedding('simple', features + 1, hidden, act=kwargs.get('act', None))
        self.mp_layers = nn.ModuleList([construct_mp_layer('fixed', hidden=hidden,**kwargs) for _ in range(iters)])
        self.readout = construct_readout(readout, hidden, hidden)
        #self.adjacency_matrix = self.set_adjacency_matrix(features=features,**kwargs)
        self.adjacency_matrix = construct_adjacency(matrix=matrix, features=features, **kwargs)

        logger = kwargs.get('logger', None)
        self.monitoring = logger is not None
        if self.monitoring:
            self.set_monitors()
            self.initialize_monitors(logger)

    def set_monitors(self):
        self.dij_histogram = Histogram('dij', n_bins=10, rootname='dij', append=True)
        self.dij_matrix_monitor = BatchMatrixMonitor('dij')
        #self.dij_histogram.initialize(None, os.path.join(logger.plotsdir, 'dij_histogram'))
        #self.dij_matrix_monitor.initialize(None, os.path.join(logger.plotsdir, 'adjacency_matrix'))
        self.monitors = [self.dij_matrix_monitor, self.dij_histogram]

    def initialize_monitors(self, logger):
        for m in self.monitors: m.initialize(None, logger.plotsdir)

    def set_adjacency_matrix(self, **kwargs):
        pass

    def forward(self, jets, mask=None, **kwargs):
        h = self.embedding(jets)
        dij = self.adjacency_matrix(jets, mask=mask, **kwargs)
        for mp in self.mp_layers:
            h, _ = mp(h=h, mask=mask, dij=dij, **kwargs)
        out = self.readout(h)

        # logging
        if self.monitoring:
            self.logging(dij=dij, mask=mask, **kwargs)

        return out, _

    def logging(self, dij=None, mask=None, epoch=None, iters=None, **kwargs):
        if epoch is not None and epoch % 20 == 0:
            #import ipdb; ipdb.set_trace()
            nonmask_ends = [int(torch.sum(m,0)[0]) for m in mask.data]
            dij_hist = [d[:nme, :nme].contiguous().view(-1) for d, nme in zip(dij, nonmask_ends)]
            dij_hist = torch.cat(dij_hist,0)
            self.dij_histogram(values=dij_hist)
            if iters == 0:
                self.dij_histogram.visualize('epoch-{}/histogram'.format(epoch))
                #self.dij_histogram.clear()
                self.dij_matrix_monitor(dij=dij)
                self.dij_matrix_monitor.visualize('epoch-{}/M'.format(epoch), n=10)


class PhysicsNMP(FixedAdjacencyNMP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    #def set_adjacency_matrix(self, **kwargs):
    #    return construct_physics_based_adjacency_matrix(
    #                    alpha=kwargs.pop('alpha', None),
    #                    R=kwargs.pop('R', None),
    #                    trainable_physics=kwargs.pop('trainable_physics', None)
    #                    )

class PhysicsPlusLearnedNMP(FixedAdjacencyNMP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def physics_component(self):
        return torch.sigmoid(self._physics_component)

    @physics_component.setter
    def physics_component(self, value):
        self._physics_component = torch.FloatTensor([float(value)])
        if self.learned_tradeoff:
            self._physics_component = nn.Parameter(self._physics_component)
        else:
            self._physics_component = Variable(self._physics_component)
            if torch.cuda.is_available():
                self._physics_component = self._physics_component.cuda()

    def set_adjacency_matrix(self, **kwargs):
        self.learned_tradeoff = kwargs.pop('learned_tradeoff', False)
        self.physics_component = kwargs.pop('physics_component', None)

        self.learned_matrix = construct_adjacency_matrix_layer(
                    kwargs.get('adaptive_matrix', None),
                    hidden=kwargs.get('features', None) + 1,
                    symmetric=kwargs.get('symmetric', None),
                    m_out=None
                    )

        self.physics_matrix = construct_physics_based_adjacency_matrix(
                        alpha=kwargs.pop('alpha', None),
                        R=kwargs.pop('R', None),
                        trainable_physics=kwargs.pop('trainable_physics', None),
                        m_out=None
                        )

        self.m_out = kwargs.pop('m_out')

        def combined_matrix(jets, epoch=None, iters=None, **kwargs):
            mask = kwargs.get('mask', None)
            P = self.physics_matrix(jets, mask)
            L = self.learned_matrix(jets, mask)
            x = self.physics_component
            out = x * P + (1 - x) * L
            out = self.m_act(out, mask=mask)

            # logging
            if self.monitoring and epoch is not None and iters == 0:
                self.component_monitor(physics_component=self.physics_component)
                self.component_monitor.visualize('physics_component')
                if epoch % 20 == 0:
                    self.physics_matrix_monitor(physics=P)
                    self.physics_matrix_monitor.visualize('epoch-{}/P'.format(epoch), n=10)
                    self.learned_matrix_monitor(learned=L)
                    self.learned_matrix_monitor.visualize('epoch-{}/L'.format(epoch), n=10)

            return out
        return combined_matrix

    def set_monitors(self):
        super().set_monitors()
        self.component_monitor = Collect('physics_component', fn='last')
        self.physics_matrix_monitor = BatchMatrixMonitor('physics')
        self.learned_matrix_monitor = BatchMatrixMonitor('learned')

        self.monitors.extend([self.component_monitor, self.physics_matrix_monitor, self.learned_matrix_monitor])



class EyeNMP(FixedAdjacencyNMP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_adjacency_matrix(self, **kwargs):
        def eye(jets, mask=None, **kwargs):
            bs, sz, _ = jets.size()
            matrix = Variable(torch.eye(sz).unsqueeze(0).repeat(bs, 1, 1))
            if torch.cuda.is_available():
                matrix = matrix.cuda()
            if mask is None:
                return matrix
            return mask * matrix
        return eye

class OnesNMP(FixedAdjacencyNMP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_adjacency_matrix(self, **kwargs):
        def ones(jets, mask=None, **kwargs):
            bs, sz, _ = jets.size()
            matrix = Variable(torch.ones(bs, sz, sz))
            if torch.cuda.is_available():
                matrix = matrix.cuda()
            if mask is None:
                return matrix
            return mask * matrix
        return ones

class LearnedFixedNMP(FixedAdjacencyNMP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_adjacency_matrix(self, **kwargs):
        matrix = construct_adjacency_matrix_layer(
                    kwargs.get('adaptive_matrix', None),
                    hidden=kwargs.get('features', None) + 1,
                    symmetric=kwargs.get('symmetric', None)
                    )
        return matrix

class PhysicsStackNMP(nn.Module):
    def __init__(self,
        features=None,
        hidden=None,
        iters=None,
        readout=None,
        scales=None,
        mp_layer=None,
        pooling_layer=None,
        **kwargs
        ):
        super().__init__()
        self.iters = iters
        self.embedding = construct_embedding('simple', features + 1, hidden, act=kwargs.get('act', None))
        self.physics_nmp = PhysicsNMP(features, hidden, 1, readout='constant', **kwargs)
        self.readout = construct_readout(readout, hidden, hidden)
        self.attn_pools = nn.ModuleList([construct_pooling_layer(pooling_layer, scales[i], hidden) for i in range(len(scales))])
        self.nmps = nn.ModuleList([construct_mp_layer(mp_layer, hidden=hidden, **kwargs) for _ in range(len(scales))])

    def forward(self, jets, mask=None, **kwargs):
        h, _ = self.physics_nmp(jets, mask, **kwargs)
        for pool, nmp in zip(self.attn_pools, self.nmps):
            h = pool(h)
            h, A = nmp(h=h, mask=None, **kwargs)
        out = self.readout(h)
        return out, A