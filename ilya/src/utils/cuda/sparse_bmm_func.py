import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from utils.cuda.sparse_bmm import sparse_bmm
from utils.cuda.batch_csr import batch_csr
import numpy as np
import time

forward_cached_matrices = {}
backward_cached_matrices = {}

class SparseBMMFunc(torch.autograd.Function):
    def __init__(self):
        self.mat_id = None

    def forward(self, matrix1, matrix2):
        global forward_cached_matrices
        global backward_cached_matrices

        self.save_for_backward(matrix1, matrix2)

        col_ind, col_ptr = batch_csr(matrix1._indices(), matrix1.size())

        """
        result = sparse_bmm(matrix1.values(), col_ind, col_ptr, matrix1.size(), matrix2)

        x = torch.bmm(matrix1.to_dense(), matrix2)

        print((x - result).abs().max())
        """
        return sparse_bmm(matrix1._values(), col_ind, col_ptr, matrix1.size(), matrix2)

    def backward(self, grad_output):
        global forward_cached_matrices
        global backward_cached_matrices

        matrix1, matrix2 = self.saved_tensors
        grad_matrix1 = grad_matrix2 = None

        matrix1_t = matrix1.transpose(2, 1).coalesce()
        col_ind, col_ptr = batch_csr(matrix1_t._indices(), matrix1_t.size())

        grad_matrix2 = sparse_bmm(matrix1_t._values(), col_ind, col_ptr, matrix1_t.size(), grad_output)

        return grad_matrix1, grad_matrix2

if __name__ == "__main__":
    tmp = torch.zeros(1).cuda()

    indices, values, size = np.load(open('utils/tmp_data/Di_.pt', 'rb'))

    a_ = torch.sparse.FloatTensor(indices, values, size)

    a_ = Variable(a_.transpose(2, 1).coalesce()).cuda()

    batch_size, num_nodes, num_faces = a_.size()

    a = Variable(a_.data.to_dense())

    for _ in range(10):
        tmp = torch.randn(batch_size, num_faces, 16)
        b = Variable(tmp, requires_grad=True).cuda()
        b_ = Variable(tmp, requires_grad=True).cuda()


        torch.cuda.synchronize()
        time1 = time.time()
        result = torch.bmm(a, b)
        torch.cuda.synchronize()
        time2 = time.time()
        print("{} CuBlas dense bmm".format(time2 - time1))

        torch.cuda.synchronize()
        time1 = time.time()
        my_result = SparseBMMFunc()(a_, b_)
        torch.cuda.synchronize()
        time2 = time.time()
        print("{} My sparse bmm".format(time2 - time1))

        my_result.sum().backward()
        result.sum().backward()

        print("{} Diff".format((b_.data-b.data).abs().max()))
        print("{} Diff".format((result.data-my_result.data).abs().max()))
