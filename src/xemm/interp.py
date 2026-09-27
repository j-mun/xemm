import jax.numpy as jp


def _query(x, xp, extrap):
  if not extrap:
    return jp.clip(x, xp[0], xp[-1])
  return x


def linear(x, xp, fp, extrap=False):
  """Linearly interpolate values sampled at sorted coordinates ``xp``."""
  x = jp.asarray(x)
  xp = jp.asarray(xp)
  fp = jp.asarray(fp)

  x = _query(x, xp, extrap)
  indices = jp.clip(jp.searchsorted(xp, x, side='right') - 1, 0, xp.size - 2)
  x0 = xp[indices]
  x1 = xp[indices + 1]
  y0 = fp[indices]
  y1 = fp[indices + 1]
  return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def cubic(x, xp, fp, extrap=False):
  """Not-a-knot cubic-spline interpolation for one-dimensional samples."""
  x = jp.asarray(x)
  xp = jp.asarray(xp)
  fp = jp.asarray(fp)
  x = _query(x, xp, extrap)
  if xp.size < 4:
    raise ValueError('cubic interpolation requires at least four samples')

  widths = jp.diff(xp)
  slopes = jp.diff(fp) / widths
  size = xp.size
  matrix = jp.zeros((size, size), dtype=xp.dtype)
  rhs = jp.zeros(size, dtype=jp.result_type(xp, fp))

  matrix = matrix.at[0, 0:3].set(jp.array([widths[1], -widths[0] - widths[1], widths[0]]))
  matrix = matrix.at[-1, -3:].set(jp.array([widths[-1], -widths[-2] - widths[-1], widths[-2]]))
  interior = jp.arange(1, size - 1)
  matrix = matrix.at[interior, interior-1].set(widths[:-1])
  matrix = matrix.at[interior, interior  ].set(2 * (widths[:-1] + widths[1:]))
  matrix = matrix.at[interior, interior+1].set(widths[1:])
  rhs = rhs.at[interior].set(6 * (slopes[1:] - slopes[:-1]))
  second_derivatives = jp.linalg.solve(matrix, rhs)

  indices = jp.clip(jp.searchsorted(xp, x, side='right') - 1, 0, size - 2)
  width = widths[indices]
  left = xp[indices]
  right = xp[indices + 1]
  left_weight = (right - x) / width
  right_weight = (x - left) / width
  return (
    left_weight * fp[indices]
    + right_weight * fp[indices + 1]
    + ((left_weight ** 3 - left_weight) * second_derivatives[indices]
       + (right_weight ** 3 - right_weight) * second_derivatives[indices + 1])
      * width ** 2 / 6
  )