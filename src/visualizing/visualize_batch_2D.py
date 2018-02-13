from PIL import Image
import torch
import numpy
import os
def visualize_batch_2D(tensor, logger, path_to_visualizations):
    '''
    Input: B x N x M tensor with values in [0, 1]
    Saves B grayscale images to the savedir
    '''
    if isinstance(tensor, torch.autograd.Variable):
        tensor = tensor.data
    if isinstance(tensor, torch.Tensor):
        tensor = tensor.numpy()
    assert isinstance(tensor, numpy.ndarray)
    assert tensor.max() <= 1.0
    assert tensor.min() >= 0.0
    savedir = os.path.join(logger.plotsdir, path_to_visualizations)
    if not os.path.exists(savedir):
        os.makedirs(savedir)
    for i, t in enumerate(tensor):
        im = Image.fromarray(t*256)
        im.save("{}/{}.tiff".format(savedir, i+1))