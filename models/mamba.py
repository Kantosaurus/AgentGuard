# reference https://arxiv.org/pdf/2312.00752

import torch.nn as nn
import torch
from torch import Tensor
from torch.functional import F

class MambaSSM(nn.Module):

    def __init__(self, state_dim, input_dim, output_dim):
        super().__init__()

        self.state_dim = state_dim

        # static A (diagonal in real Mamba)
        self.A = nn.Parameter(torch.randn(state_dim))

        # projections that generate dynamic parameters
        self.B_proj = nn.Linear(input_dim, state_dim)
        self.C_proj = nn.Linear(input_dim, state_dim)
        self.delta_proj = nn.Linear(input_dim, state_dim)

        self.D = nn.Linear(input_dim, output_dim)
        self.out_proj = nn.Linear(state_dim, output_dim)

    def forward(self, u):
        # Reference: (Gu & Dao, 2023, p.8)

        # dynamic parameters
        B = self.B_proj(u) # [Batch,Sequence,State_Dim]
        C = self.C_proj(u) # [Batch,Sequence,State_Dim]
        delta = F.softplus(self.delta_proj(u))

        # diagonal state transition
        A = torch.exp(delta * self.A) # [Batch,Sequence,State_Dim]

        b = B * u.unsqueeze(-1)        # input contribution

        # prefix product
        A_prefix = torch.cumprod(A, dim=1)

        # compute states
        x = A_prefix * torch.cumsum(b / A_prefix, dim=1)

        # output
        y = (C * x).sum(-1)

        return y
    
class MambaBlock(nn.Module):
    def __init__(self, d_model, state_dim, kernel_size=3):
        super().__init__()

        # First linear to expand features (split into Conv->SSM + gate)
        self.in_proj = nn.Linear(d_model, 2 * d_model)
        
        # Conv1D over sequence for SSM branch (kernel along time dimension)
        # Conv1d expects (B, C, T), so we'll transpose in forward
        self.conv = nn.Conv1d(d_model, d_model, kernel_size, padding=kernel_size//2)
        
        # SSM
        self.ssm = MambaSSM(state_dim, d_model, d_model)
        
        # Output projection
        self.out_proj = nn.Linear(d_model, d_model)

    def forward(self, x):
        # x: [B, T, d_model]
        x_proj = self.in_proj(x) # [Batch,Sequence,2 * State_Dim]
        x_ssm, x_gate = x_proj.chunk(2, dim=-1)  # split

        # --- SSM branch with conv + SiLU ---
        # Conv1d expects (B, C, T)
        # Linear Projection -> Conv -> SiLU -> SSM
        x_conv = x_ssm.transpose(1, 2) # [Batch,State_Dim,Sequence]
        x_conv = self.conv(x_conv) # [Batch,State_Dim,Sequence]
        x_conv = F.silu(x_conv)
        x_conv = x_conv.transpose(1, 2)# [Batch,Sequence.State_Dim]

        ssm_out = self.ssm(x_conv)

        # --- Gate branch ---
        # Linear Projection -> SiLU
        gate = F.silu(x_gate)

        # --- Combine ---
        # SSM Branch Multiply Gate Branch
        y = ssm_out * gate
        return self.out_proj(y)