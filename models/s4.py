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
            self.A = nn.Parameter(torch.tril(torch.randn(state_dim, state_dim) * 0.01))
            self.B = nn.Parameter(torch.randn(state_dim, input_dim) * 0.01)

        # B is the control matrix
        # C is the output matrix
        self.C = nn.Parameter(torch.randn(output_dim,state_dim) * 0.01)
        # D is the command matrix
        self.D = nn.Parameter(torch.randn(output_dim,input_dim) * 0.01)


    def forward(self, u: torch.Tensor):
        batch, _, _ = u.shape
        state_dim = self.state_dim

        # Compute Bu for all timesteps: [batch, seq_len, state_dim]
        Bu = u @ self.B.T

        # Transpose to match solve_triangular input shape: [batch, state_dim, seq_len]
        Bu_t = Bu.transpose(1, 2)

        # Construct I - A for recurrence
        I_minus_A = torch.eye(state_dim, device=u.device, dtype=u.dtype) - self.A  # [state_dim, state_dim]

        # Expand to batch for batched solve
        I_minus_A_batched = I_minus_A.unsqueeze(0).expand(batch, -1, -1)  # [batch, state_dim, state_dim]

        # Batched lower-triangular solve
        x_seq_t = torch.linalg.solve_triangular(
            I_minus_A_batched,  # [batch, state_dim, state_dim]
            Bu_t,               # [batch, state_dim, seq_len]
            upper=False
        )  # [batch, state_dim, seq_len]

        # Transpose back to [batch, seq_len, state_dim]
        x_seq = x_seq_t.transpose(1, 2)

        # Compute outputs
        y = x_seq @ self.C.T + u @ self.D.T  # [batch, seq_len, output_dim]

        return y



