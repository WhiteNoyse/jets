import torch
from torch.optim import Adam, lr_scheduler
import copy
import numpy as np
import logging
import pickle
import time
import os
import argparse

from sklearn.model_selection import train_test_split

from data_ops.wrapping import wrap
from data_ops.wrapping import unwrap
from data_ops.wrapping import wrap_X
from data_ops.wrapping import unwrap_X

from misc.constants import *
from misc.handlers import ExperimentHandler
from misc.loggers import StatsLogger

from monitors.losses import *

from experiment import convert_args

from loading import load_data
from loading import load_tf
from loading import crop
from loading import load_model

''' ARGUMENTS '''
'''----------------------------------------------------------------------- '''
parser = argparse.ArgumentParser(description='Jets')

# data args
parser.add_argument("--data_dir", type=str, default=DATA_DIR)
parser.add_argument("-n", "--n_train", type=int, default=-1)
parser.add_argument("--n_valid", type=int, default=VALID)
parser.add_argument("--dont_add_cropped", action='store_true', default=False)
parser.add_argument("-p", "--pileup", action='store_true', default=False)
parser.add_argument("--root_dir", default=MODELS_DIR)

# general model args
parser.add_argument("-m", "--model_type", help="name of the model you want to train - look in constants.py for the model list", type=str, default="mpnn")
parser.add_argument("--features", type=int, default=FEATURES)
parser.add_argument("--hidden", type=int, default=HIDDEN)

# logging args
parser.add_argument("-s", "--silent", action='store_true', default=False)
parser.add_argument("-v", "--verbose", action='store_true', default=False)
parser.add_argument("--visualizing", action='store_true', default=False)
parser.add_argument("--slurm_job_id", default=0)

# loading previous models args
parser.add_argument("-l", "--load", help="model directory from which we load a state_dict", type=str, default=None)
parser.add_argument("-r", "--restart", help="restart a loaded model from where it left off", action='store_true', default=False)

# training args
parser.add_argument("-e", "--epochs", type=int, default=EPOCHS)
parser.add_argument("-b", "--batch_size", type=int, default=BATCH_SIZE)
parser.add_argument("-a", "--step_size", type=float, default=STEP_SIZE)
parser.add_argument("-d", "--decay", type=float, default=DECAY)
parser.add_argument("--clip", type=float, default=None)

# computing args
parser.add_argument("--seed", help="Random seed used in torch and numpy", type=int, default=None)
parser.add_argument("-g", "--gpu", type=str, default="")

# MPNN
parser.add_argument("-i", "--iters", type=int, default=ITERS)
parser.add_argument("--scales", nargs='+', type=int, default=SCALES)
parser.add_argument("--mp", type=str, default='van', help='type of message passing layer')
parser.add_argument("--pool", type=str, default='attn', help='type of pooling layer')
parser.add_argument("--predict", type=str, default=0, help='type of prediction layer')
parser.add_argument("--matrix", type=str, default=0, help='type of adaptive matrix layer')
parser.add_argument("--sym", action='store_true', default=False)
parser.add_argument("--pool_first", action='store_true', default=False)

# Physics MPNN
parser.add_argument("--trainable", action='store_true', default=False)

# debugging
parser.add_argument("--debug", help="sets everything small for fast model debugging. use in combination with ipdb", action='store_true', default=False)

args = parser.parse_args()
args.train = True
if args.debug:
    args.hidden = 7
    args.batch_size = 5
    args.verbose = True
    args.epochs = 3
    args.n_train = 1000
    args.seed = 1

os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu

if args.n_train <= 5 * args.n_valid and args.n_train > 0:
    args.n_valid = args.n_train // 5

if args.pileup:
    args.dataset = 'pileup'
else:
    args.dataset = 'original'

def train(args):
    t_start = time.time()

    args, architecture = convert_args(args)

    eh = ExperimentHandler(args)

    ''' DATA '''
    '''----------------------------------------------------------------------- '''
    logging.warning("Loading data...")

    tf = load_tf(args.data_dir, "{}-train.pickle".format(DATASETS[args.dataset]))
    X, y = load_data(args.data_dir, "{}-train.pickle".format(DATASETS[args.dataset]))
    for ij, jet in enumerate(X):
        jet["content"] = tf.transform(jet["content"])

    if args.n_train > 0:
        indices = torch.randperm(len(X)).numpy()[:args.n_train]
        X = [X[i] for i in indices]
        y = y[indices]

    logging.warning("Splitting into train and validation...")

    X_train, X_valid_uncropped, y_train, y_valid_uncropped = train_test_split(X, y, test_size=args.n_valid, random_state=0)
    logging.warning("\traw train size = %d" % len(X_train))
    logging.warning("\traw valid size = %d" % len(X_valid_uncropped))

    X_valid, y_valid, cropped_indices, w_valid = crop(X_valid_uncropped, y_valid_uncropped, return_cropped_indices=True, pileup=args.pileup)
    # add cropped indices to training data
    if not args.dont_add_cropped:
        X_train.extend([x for i, x in enumerate(X_valid_uncropped) if i in cropped_indices])
        y_train = [y for y in y_train]
        y_train.extend([y for i, y in enumerate(y_valid_uncropped) if i in cropped_indices])
        y_train = np.array(y_train)
    logging.warning("\tfinal train size = %d" % len(X_train))
    logging.warning("\tfinal valid size = %d" % len(X_valid))

    ''' MODEL '''
    '''----------------------------------------------------------------------- '''
    # Initialization
    logging.info("Initializing model...")
    if args.load is None:
        model_kwargs = {
            'features': args.features,
            'hidden': args.hidden,
            'iters': args.iters,
            'scales': args.scales,
            'pooling_layer':architecture.pooling_layer,
            'mp_layer':architecture.message_passing_layer,
            'symmetric':args.sym,
            'pool_first':args.pool_first,
            'adaptive_matrix':architecture.matrix,
            'trainable':args.trainable
        }
        model = architecture.predict(architecture.transform, **model_kwargs)
        settings = {
            "transform": args.model_type,
            "predict": architecture.predict,
            "model_kwargs": model_kwargs,
            "step_size": args.step_size,
            "args": args,
            }
    else:
        load_model(args.load)
        if args.restart:
            args.step_size = settings["step_size"]

    logging.warning(model)
    out_str = 'Number of parameters: {}'.format(sum(np.prod(p.data.numpy().shape) for p in model.parameters()))
    logging.warning(out_str)

    if torch.cuda.is_available():
        logging.warning("Moving model to GPU")
        model.cuda()
        logging.warning("Moved model to GPU")

    eh.signal_handler.set_model(model)

    ''' OPTIMIZER AND LOSS '''
    '''----------------------------------------------------------------------- '''
    logging.info("Building optimizer...")
    optimizer = Adam(model.parameters(), lr=args.step_size)
    scheduler = lr_scheduler.ExponentialLR(optimizer, gamma=args.decay)
    #scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.5)

    n_batches = int(len(X_train) // args.batch_size)

    def loss(y_pred, y):
        l = log_loss(y, y_pred.squeeze(1)).mean()
        return l

        ''' VALIDATION '''
    '''----------------------------------------------------------------------- '''
    def callback(epoch, iteration, model):

        if iteration % n_batches == 0:
            t0 = time.time()
            model.eval()

            offset = 0; train_loss = []; valid_loss = []
            yy, yy_pred = [], []
            for i in range(len(X_valid) // args.batch_size):
                idx = slice(offset, offset+args.batch_size)
                Xt, yt = X_train[idx], y_train[idx]
                X_var = wrap_X(Xt); y_var = wrap(yt)
                tl = unwrap(loss(model(X_var), y_var)); train_loss.append(tl)
                X = unwrap_X(X_var); y = unwrap(y_var);

                #Xt, yt = X_train[idx], y_train[idx]
                #X_var = wrap_X(Xt); y_var = wrap(yt)
                #tl = unwrap(loss(model(X_var), y_var)); train_loss.append(tl)
                #X = unwrap_X(X_var); y = unwrap(y_var)

                Xv, yv = X_valid[idx], y_valid[idx]
                X_var = wrap_X(Xv); y_var = wrap(yv)
                y_pred = model(X_var)
                vl = unwrap(loss(y_pred, y_var)); valid_loss.append(vl)
                Xv = unwrap_X(X_var); yv = unwrap(y_var); y_pred = unwrap(y_pred)
                yy.append(yv); yy_pred.append(y_pred)

                offset+=args.batch_size

            train_loss = np.mean(np.array(train_loss))
            valid_loss = np.mean(np.array(valid_loss))
            yy = np.concatenate(yy, 0)
            yy_pred = np.concatenate(yy_pred, 0)

            t1=time.time()
            logdict = dict(
                epoch=epoch,
                iteration=iteration,
                yy=yy,
                yy_pred=yy_pred,
                w_valid=w_valid[:len(yy_pred)],
                #w_valid=w_valid,
                train_loss=train_loss,
                valid_loss=valid_loss,
                settings=settings,
                model=model,
                logtime=np.log((t1-t0) / len(X_valid)),
                time=((t1-t_start))
            )
            eh.log(**logdict)

            scheduler.step(valid_loss)
            model.train()

    ''' TRAINING '''
    '''----------------------------------------------------------------------- '''
    eh.save(model, settings)
    logging.warning("Training...")
    iteration=1
    for i in range(args.epochs):
        logging.info("epoch = %d" % i)
        logging.info("step_size = %.8f" % settings['step_size'])
        t0 = time.time()
        for _ in range(n_batches):
            iteration += 1
            model.train()
            optimizer.zero_grad()
            start = torch.round(torch.rand(1) * (len(X_train) - args.batch_size)).numpy()[0].astype(np.int32)
            idx = slice(start, start+args.batch_size)
            X, y = X_train[idx], y_train[idx]
            X_var = wrap_X(X); y_var = wrap(y)
            l = loss(model(X_var), y_var)
            l.backward()
            if args.clip is not None:
                torch.nn.utils.clip_grad_norm(model.parameters(), args.clip)
            optimizer.step()
            X = unwrap_X(X_var); y = unwrap(y_var)
            callback(i, iteration, model)
        t1 = time.time()
        logging.info("Epoch took {} seconds".format(t1-t0))

        scheduler.step()
        settings['step_size'] = args.step_size * (args.decay) ** (i + 1)

    eh.finished()


if __name__ == "__main__":
    train(args)
