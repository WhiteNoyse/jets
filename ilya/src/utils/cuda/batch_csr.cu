#define BATCH_SIZE ${BATCH_SIZE}
#define NUM_ROWS ${NUM_ROWS}

extern "C"
__global__ void batch_csr(const long *indices, long *col_ind, long *col_ptr, long nnz) {
  long ind = blockIdx.x * blockDim.x + threadIdx.x;
  if (!(ind < nnz)) {
    return;
  }
  long batch_id = indices[ind];
  long row_id = indices[ind + nnz];
  long col_id = indices[ind + 2 * nnz];

  long prev_batch_id = -1;
  if (ind > 0) {
    prev_batch_id = indices[ind - 1];
  }

  long prev_row_id = -1;
  if (ind > 0) {
    prev_row_id = indices[ind - 1 + nnz];
  }

  if (ind < nnz) {
    col_ind[ind] = col_id;
  }

  if ((batch_id != prev_batch_id) || (row_id != prev_row_id)) {
    col_ptr[batch_id * (NUM_ROWS + 1) + row_id] = ind;

    if (batch_id > 0 && row_id == 0) {
      col_ptr[prev_batch_id * (NUM_ROWS + 1) + prev_row_id + 1] = ind;
    }
  }

  if (ind + 1 == nnz) {
    col_ptr[batch_id * (NUM_ROWS + 1) + row_id + 1] = ind + 1;
  }
}
