#pragma once

#ifdef constrain
#undef constrain
#endif

namespace gt7
{
inline float constrain(float x, float a, float b)
{
  if (x < a)
  {
    return a;
  }
  if (x > b)
  {
    return b;
  }
  return x;
}
}  // namespace gt7