# s4 model implementation
# References: https://huggingface.co/blog/lbourdois/get-on-the-ssm-train


import torch.nn as nn
import torch
from torch import Tensor
from utils.discretization import hippo_discretization

class S4Model(nn.Module):
    
    def __init__(self,
                 state_dim: int,
                 input_dim: int,
                 output_dim: int,
                 seq_len: int,
                 HiPPO: bool = False,
                 ):

        super().__init__()
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        self.state_dim = state_dim
        self.seq_len = seq_len

        # A is the state matrix, either using HiPPO-Legendre Matrix A or random
        if HiPPO:
            discrete_A, discrete_B = hippo_discretization(state_dim)
            self.A = nn.Parameter(discrete_A)
            self.B = nn.Parameter(discrete_B.repeat(1,input_dim))
        else:
            self.A = nn.Parameter(torch.randn(state_dim,state_dim) * 0.01)
            self.B = nn.Parameter(torch.randn(state_dim,input_dim) * 0.01)

        # B is the control matrix
        # C is the output matrix
        self.C = nn.Parameter(torch.randn(output_dim,state_dim) * 0.01)
        # D is the command matrix
        self.D = nn.Parameter(torch.randn(output_dim,input_dim) * 0.01)


    def forward(self,u: Tensor):
        batch_size = u.size(0)
        x = torch.zeros(batch_size, self.state_dim, device=u.device)
        y_seq = []

        for t in range(self.seq_len):
            u_t = u[:, t, :]
            # State update: x_t+1 = A x_t + B u_t
            x = x @ self.A.T + u_t @ self.B.T
            # Output: y_t = C x_t + D u_t
            y_t = x @ self.C.T + u_t @ self.D.T
            y_seq.append(y_t.unsqueeze(1))

        y = torch.cat(y_seq, dim=1)
        return y



