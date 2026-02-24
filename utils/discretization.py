import torch

def hippo_discretization(state_dim, dt = 1.0):
    A = torch.zeros(state_dim, state_dim)
    B = torch.zeros(state_dim,1)

    for n in range(state_dim):
        for k in range(state_dim):
            if n > k:
                A[n,k] = -(2*n + 1)**0.5 * (2*k+1)**0.5
            elif n == k:
                A[n,k] = -(n+1)
            else:
                A[n,k] = 0.0
        B[n, 0] = 1.0

    I = torch.eye(state_dim)

    discrete_A = torch.inverse((I - (dt/2) * A)) @ (I + (dt/2)*A)
    discrete_B = torch.inverse(I - (dt/2)*A) @ (dt)*B

    return discrete_A, discrete_B