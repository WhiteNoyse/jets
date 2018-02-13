import numpy as np
import copy
import pickle
# Data loading related

def load_from_pickle(filename, n_jets):
    jets = []
    fd = open(filename, "rb")

    for i in range(n_jets):
        jet = pickle.load(fd)
        jets.append(jet)

    fd.close()

    return jets


# Jet related

def _pt(v):
    pz = v[2]
    p = (v[0:3] ** 2).sum() ** 0.5
    eta = 0.5 * (np.log(p + pz) - np.log(p - pz))
    pt = p / np.cosh(eta)
    return pt


def permute_by_pt(jet, root_id=None):
    # ensure that the left sub-jet has always a larger pt than the right

    if root_id is None:
        root_id = jet["root_id"]

    if jet["tree"][root_id][0] != -1:
        left = jet["tree"][root_id][0]
        right = jet["tree"][root_id][1]

        pt_left = _pt(jet["content"][left])
        pt_right = _pt(jet["content"][right])

        if pt_left < pt_right:
            jet["tree"][root_id][0] = right
            jet["tree"][root_id][1] = left

        permute_by_pt(jet, left)
        permute_by_pt(jet, right)

    return jet


def rewrite_content(jet):
    jet = copy.deepcopy(jet)

    if jet["content"].shape[1] == 5:
        pflow = jet["content"][:, 4].copy()

    content = jet["content"]
    tree = jet["tree"]

    def _rec(i):
        if tree[i, 0] == -1:
            pass
        else:
            _rec(tree[i, 0])
            _rec(tree[i, 1])
            c = content[tree[i, 0]] + content[tree[i, 1]]
            content[i] = c

    _rec(jet["root_id"])

    if jet["content"].shape[1] == 5:
        jet["content"][:, 4] = pflow

    return jet


def extract(jet, pflow=False):
    # per node feature extraction

    jet = copy.deepcopy(jet)

    s = jet["content"].shape

    if not pflow:
        content = np.zeros((s[0], 7))
    else:
        # pflow value will be one-hot encoded
        content = np.zeros((s[0], 7+4))

    for i in range(len(jet["content"])):
        px = jet["content"][i, 0]
        py = jet["content"][i, 1]
        pz = jet["content"][i, 2]

        p = (jet["content"][i, 0:3] ** 2).sum() ** 0.5
        eta = 0.5 * (np.log(p + pz) - np.log(p - pz))
        theta = 2 * np.arctan(np.exp(-eta))
        pt = p / np.cosh(eta)
        phi = np.arctan2(py, px)

        content[i, 0] = p
        content[i, 1] = eta if np.isfinite(eta) else 0.0
        content[i, 2] = phi
        content[i, 3] = jet["content"][i, 3]
        content[i, 4] = (jet["content"][i, 3] /
                         jet["content"][jet["root_id"], 3])
        content[i, 5] = pt if np.isfinite(pt) else 0.0
        content[i, 6] = theta if np.isfinite(theta) else 0.0

        if pflow:
            if jet["content"][i, 4] >= 0:
                content[i, 7+int(jet["content"][i, 4])] = 1.0

    jet["content"] = content

    return jet


def randomize(jet):
    # build a random tree

    jet = copy.deepcopy(jet)

    leaves = np.where(jet["tree"][:, 0] == -1)[0]
    nodes = [n for n in leaves]
    content = [jet["content"][n] for n in nodes]
    nodes = [i for i in range(len(nodes))]
    tree = [[-1, -1] for n in nodes]
    pool = [n for n in nodes]
    next_id = len(nodes)

    while len(pool) >= 2:
        i = np.random.randint(len(pool))
        left = pool[i]
        del pool[i]
        j = np.random.randint(len(pool))
        right = pool[j]
        del pool[j]

        nodes.append(next_id)
        c = (content[left] + content[right])

        if len(c) == 5:
            c[-1] = -1

        content.append(c)
        tree.append([left, right])
        pool.append(next_id)
        next_id += 1

    jet["content"] = np.array(content)
    jet["tree"] = np.array(tree).astype(int)
    jet["root_id"] = len(jet["tree"]) - 1

    return jet


def sequentialize_by_pt(jet, reverse=False):
    # transform the tree into a sequence ordered by pt

    jet = copy.deepcopy(jet)

    leaves = np.where(jet["tree"][:, 0] == -1)[0]
    nodes = [n for n in leaves]
    content = [jet["content"][n] for n in nodes]
    nodes = [i for i in range(len(nodes))]
    tree = [[-1, -1] for n in nodes]
    pool = sorted([n for n in nodes],
                  key=lambda n: _pt(content[n]),
                  reverse=reverse)
    next_id = len(pool)

    while len(pool) >= 2:
        right = pool[-1]
        left = pool[-2]
        del pool[-1]
        del pool[-1]

        nodes.append(next_id)
        c = (content[left] + content[right])

        if len(c) == 5:
            c[-1] = -1

        content.append(c)
        tree.append([left, right])
        pool.append(next_id)
        next_id += 1

    jet["content"] = np.array(content)
    jet["tree"] = np.array(tree).astype(int)
    jet["root_id"] = len(jet["tree"]) - 1

    return jet
