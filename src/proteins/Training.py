import logging
import time
import gc
import os

import torch
import torch.nn.functional as F

from .data_ops.load_dataset import load_train_dataset
from .data_ops.ProteinLoader import ProteinLoader as DataLoader

from src.data_ops.wrapping import unwrap

from src.misc.constants import DATASETS

from src.monitors import BatchMatrixMonitor

from src.admin.utils import log_gpu_usage

from src.utils._Training import _Training

from .ModelBuilder import ModelBuilder
from .Administrator import Administrator

class Training(_Training):
    def __init__(self,
        admin_args=None,
        model_args=None,
        data_args=None,
        computing_args=None,
        training_args=None,
        optim_args=None,
        loading_args=None,
        **kwargs
        ):
        super().__init__(admin_args,
            model_args,
            data_args,
            computing_args,
            training_args,
            optim_args,
            loading_args,
            **kwargs)

    @property
    def Administrator(self):
        return Administrator

    @property
    def ModelBuilder(self):
        return ModelBuilder

    def set_debug_args(self,*args):

        admin_args,model_args, data_args, computing_args, training_args, optim_args, loading_args = super().set_debug_args(*args)

        if admin_args.debug:
            admin_args.no_email = True
            admin_args.verbose = True

            training_args.batch_size = 2
            training_args.epochs = 5

            data_args.n_train = 6
            data_args.n_valid = 6

            optim_args.lr = 0.1
            optim_args.period = 2

            computing_args.seed = 1

            model_args.hidden = 1
            model_args.iters = 1
            model_args.lf = 2

        return admin_args,model_args, data_args, computing_args, training_args, optim_args, loading_args

    def load_data(self,dataset, data_dir, n_train, n_valid, batch_size, preprocess, **kwargs):
        intermediate_dir, data_filename = DATASETS[dataset]
        data_dir = os.path.join(data_dir, intermediate_dir)
        train_dataset, valid_dataset = load_train_dataset(data_dir, data_filename,n_train, n_valid, preprocess)
        train_data_loader = DataLoader(train_dataset, batch_size, **kwargs)
        valid_data_loader = DataLoader(valid_dataset, batch_size, **kwargs)

        return train_data_loader, valid_data_loader


    def loss(self, y_pred, y, mask):
        return F.binary_cross_entropy(y_pred * mask, y * mask)

    def validation(self, model, data_loader):
        t_valid = time.time()
        model.eval()

        valid_loss = 0.
        yy, yy_pred = [], []
        mask = []
        for i, (x, x_mask, y, y_mask) in enumerate(data_loader):
            y_pred = model(x, mask=x_mask)
            vl = self.loss(y_pred, y, y_mask); valid_loss += float(unwrap(vl))
            yy.append(unwrap(y))
            yy_pred.append(unwrap(y_pred))
            mask.append(unwrap(y_mask))

        #if epoch % admin_args.lf == 0:
        #    y_matrix_monitor(matrix=y)
        #    y_matrix_monitor.visualize('epoch-{}/{}'.format(epoch, 'y'), n=10)
        #    y_pred_matrix_monitor(matrix=y_pred)
        #    y_pred_matrix_monitor.visualize('epoch-{}/{}'.format(epoch, 'y_pred'), n=10)

        valid_loss /= len(data_loader)

        t1=time.time()

        logdict = dict(
            yy=yy,
            yy_pred=yy_pred,
            mask=mask,
            #w_valid=valid_dataset.weights,
            valid_loss=valid_loss,
            model=model,
            logtime=0,
        )
        #logdict.update(train_dict)
        model.train()
        logging.info("Validation took {:.1f} seconds".format(time.time() - t_valid))


        return logdict

    def train_one_batch(self,model, batch, optimizer, administrator, epoch, batch_number, clip):
        logger = administrator.logger
        (x, x_mask, y, y_mask) = batch

        # forward
        model.train()
        optimizer.zero_grad()
        y_pred = model(x, mask=x_mask, logger=logger, epoch=epoch, iters=batch_number)
        l = self.loss(y_pred, y, y_mask)

        # backward
        l.backward()
        if clip is not None:
            torch.nn.utils.clip_grad_norm(model.parameters(), clip)

        if batch_number == 0:
            logging.info("COMPUTING GRADS FOR LOGGING")
            old_params = torch.cat([p.view(-1) for p in model.parameters()], 0)
            grads = torch.cat([p.grad.view(-1) for p in model.parameters() if p.grad is not None], 0)

        logging.info("POST-MODEL, PRE-OPTIM USAGE")
        log_gpu_usage()
        optimizer.step()

        if batch_number == 0:
            model_params = torch.cat([p.view(-1) for p in model.parameters()], 0)
            for m in administrator.grad_monitors:
                m(model_params=model_params, old_params=old_params, grads=grads)

        logging.info("FINAL USAGE")
        log_gpu_usage()
        logging.info("\n")

        return float(unwrap(l))
