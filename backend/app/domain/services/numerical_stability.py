import math
import numpy as np


def safe_cholesky(
    cov_matrix: np.ndarray,
    jitter: float = 1e-6,
    max_jitter: float = 1e-2,
) -> np.ndarray:
    """
    Computes a numerically stable Cholesky decomposition L of a covariance matrix:
        Sigma = L @ L.T
    where L is a lower-triangular matrix.

    If the input matrix is ill-conditioned, non-positive definite, or singular
    (e.g., due to collinear assets or numerical truncation), this function
    iteratively adds diagonal regularization (jitter * I) or clips non-positive
    eigenvalues until strict positive-definiteness is attained.

    Parameters:
        cov_matrix: Square 2D array of shape (N, N).
        jitter: Initial diagonal regularization value (default 1e-6).
        max_jitter: Maximum allowable jitter before resorting to spectral clipping (default 1e-2).

    Returns:
        Lower-triangular matrix L of shape (N, N) such that L @ L.T is strictly positive definite.
    """
    arr = np.asarray(cov_matrix, dtype=np.float64)
    if np.isnan(arr).any() or np.isinf(arr).any():
        raise ValueError("cov_matrix contiene valores NaN o Infinitos.")
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"cov_matrix debe ser cuadrada (N, N). Dimensiones dadas: {arr.shape}")

    n = arr.shape[0]
    if n == 0:
        return np.empty((0, 0), dtype=np.float64)

    # 1. Enforce exact symmetry
    sym_matrix = 0.5 * (arr + arr.T)

    if n == 1:
        val = sym_matrix[0, 0]
        if val <= 0.0:
            val = jitter
        return np.array([[math.sqrt(val)]], dtype=np.float64)

    # 2. Try standard Cholesky decomposition
    try:
        l_mat = np.linalg.cholesky(sym_matrix)
        return l_mat
    except np.linalg.LinAlgError:
        pass

    # 3. Handle non-positive definiteness by finding minimum eigenvalue
    eigvals = np.linalg.eigvalsh(sym_matrix)
    min_eig = float(np.min(eigvals))

    current_jitter = jitter
    if min_eig <= 0.0:
        current_jitter = max(jitter, abs(min_eig) + jitter)

    # 4. Iterative diagonal jitter escalation
    while current_jitter <= max_jitter:
        regularized = sym_matrix + current_jitter * np.eye(n, dtype=np.float64)
        try:
            l_mat = np.linalg.cholesky(regularized)
            return l_mat
        except np.linalg.LinAlgError:
            current_jitter *= 10.0

    # 5. Fallback: Higham-style spectral projection (clip non-positive eigenvalues)
    eigvals, eigvecs = np.linalg.eigh(sym_matrix)
    clipped_eigvals = np.maximum(eigvals, jitter)
    reconstructed = (eigvecs * clipped_eigvals) @ eigvecs.T
    reconstructed = 0.5 * (reconstructed + reconstructed.T)
    regularized = reconstructed + jitter * np.eye(n, dtype=np.float64)

    return np.linalg.cholesky(regularized)


def safe_pinv(
    matrix: np.ndarray,
    rcond: float = 1e-15,
) -> np.ndarray:
    """
    Computes the Moore-Penrose pseudoinverse A^+ using Singular Value Decomposition (SVD).
    Guarantees numerical stability for singular, collinear, or rank-deficient matrices.

    Parameters:
        matrix: 2D array of shape (M, N).
        rcond: Cutoff threshold for small singular values relative to the largest singular value.

    Returns:
        Pseudoinverse array of shape (N, M).
    """
    arr = np.asarray(matrix, dtype=np.float64)
    if np.isnan(arr).any() or np.isinf(arr).any():
        raise ValueError("matrix contiene valores NaN o Infinitos.")
    if arr.ndim != 2:
        raise ValueError(f"matrix debe ser 2D (M, N). Dimensiones dadas: {arr.ndim}")

    m, n = arr.shape
    if m == 0 or n == 0:
        return np.empty((n, m), dtype=np.float64)

    # Singular Value Decomposition: A = U * S * Vt
    u, s, vt = np.linalg.svd(arr, full_matrices=False)

    max_s = float(s[0]) if len(s) > 0 else 0.0
    if max_s <= 0.0:
        return np.zeros((n, m), dtype=np.float64)

    cutoff = rcond * max_s
    s_inv = np.zeros_like(s, dtype=np.float64)
    positive_mask = s > cutoff
    s_inv[positive_mask] = 1.0 / s[positive_mask]

    # A^+ = V * S_inv * U^T
    pinv_matrix = vt.T @ (s_inv[:, np.newaxis] * u.T)
    return pinv_matrix


def nearest_positive_definite(
    matrix: np.ndarray,
    min_eigenvalue: float = 1e-8,
) -> np.ndarray:
    """
    Finds the nearest Symmetric Positive-Definite (SPD) matrix in the Frobenius norm.
    Useful when sample covariance matrices exhibit small negative eigenvalues due to
    asynchronous market observations or missing data.
    """
    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError("matrix debe ser cuadrada (N, N).")

    # Symmetric part
    b = 0.5 * (arr + arr.T)
    eigvals, eigvecs = np.linalg.eigh(b)
    eigvals = np.maximum(eigvals, min_eigenvalue)
    spd = (eigvecs * eigvals) @ eigvecs.T
    return 0.5 * (spd + spd.T)


def matrix_condition_number(matrix: np.ndarray) -> float:
    """
    Computes the 2-norm condition number:
        kappa(A) = sigma_max / sigma_min
    A high condition number indicates an ill-conditioned system susceptible to numerical error.
    """
    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("matrix debe ser 2D.")
    s = np.linalg.svd(arr, compute_uv=False)
    if len(s) == 0:
        return 1.0
    min_s = float(s[-1])
    if min_s <= 1e-16:
        return float("inf")
    return float(s[0] / min_s)
