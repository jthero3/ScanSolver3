#!/user/bin/env python3.9

"""
-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=- LICENCE -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
Copyright © 2021 Benedict Thompson

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=--=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

                                Scan-Solver 3.0

   This program is designed to find the most efficient (time-wise) orbit for
completing a surface scan with SCAN Sat. This is done by searching orbits with
  a period p/q * T, where 'p/q' is a reduced fraction and 'T' is the sidereal
rotation period of the body being orbited, and checking for eccentricity values
               that provide complete coverage at all latitudes.

 This is done by finding values of e (between 0 and 1) for which the following
           inequality is true for all values of x (between 0 and 1):

                                   S*F >= M

                                     where

                  S = sqrt(1 + (p/q)^2 (1-e^2)^3 / (1-ex)^4)

   is the ratio of the angular speed relative the the surface to the orbital
                                angular speed,

                         F = f(a(1-e^2)/(1-ex) - R)/A

             is the field of view at each point in the orbit, and

                                 M = 180 x / q

                is the required field of view at each latitude.

                        'e' is the orbital eccentricity
                 'x' is cos of the latitude the orbit is over
           'f' is the base field of view of the scanner (in degrees)
        'a' is the semi-major axis = cube_root((p/q)^2 μ T^2 / (4 π^2))
        'μ' is the standard gravitational parameter for the body = G*m
                   'A' is the "best altitude" of the scanner

   Note that 'field of view' as used in SCAN Sat is actually the track width
 scanned, not the angle of a cone projected from the scanner. I will use it in
this way for consistency, but it is important to know when trying to understand
                          the function of each part.

       Version 1 solved circular orbits by checking that q * fov >= 180
                 Version 2 solved F >= M for elliptical orbits

       The surface component, S, added for v3.0 improves the scan times
   that can be achieved by realising that the body rotates under the orbit,
   increasing the width swept at each point. The method used keeps the maths
 simpler, but may under-estimate the gains - especially when using higher fov
                         scanners on smaller planets.
"""
from collections.abc import Iterator
from dataclasses import dataclass, field
from math import pi, sqrt, inf, gcd, ceil


@dataclass
class Body:
    radius: float
    rotation_period: float
    standard_gravity: float
    safe_altitude: float
    soi_radius: float

    geo_radius: float = field(init=False)

    def __post_init__(self):
        mu = self.standard_gravity
        t = self.rotation_period
        self.geo_radius = (mu * t**2 / (4 * pi**2)) ** (1/3)


BODIES = {
    "kerbol": Body(261_600_000, 432_000, 1.1723328e18, 600_000, inf),

    "moho": Body(250_000, 1_210_000, 1.6860938e11, 10_000, 9_646_663),

    "eve": Body(700_000, 80_500, 8.1717302e12, 90_000, 85_109_365),
    "gilly": Body(13_000, 28_255, 8.289_449_8e6, 5_000, 126_123.27),

    "kerbin": Body(600_000, 21_549.425, 3.5316e12, 70_000, 84_159_286),
    "mun": Body(200_000, 138_984.38, 6.5138398e10, 10_000, 2_429_559.1),
    "minmus": Body(60_000, 40_400, 1.7658e9, 10_000, 2_247_428.4),

    "duna": Body(320_000, 65_517.859, 3.0136321e11, 50_000, 47_921_949),
    "ike": Body(130_000, 65_517.862, 1.8568369e10, 10_000, 1_049_598.9),

    "dres": Body(138_000, 34_800, 2.1484489e10, 10_000, 32_832_840),

    "jool": Body(6_000_000, 36_000, 2.82528e14, 200_000, 2.4559852e9),
    "laythe": Body(500_000, 52_980.879, 1.962e12, 50_000, 3_723_645.8),
    "vall": Body(300_000, 105_962.09, 2.074815e11, 25_000, 2_406_401.4),
    "tylo": Body(600_000, 211_926.36, 2.82528e12, 30_000, 10_856_518),
    "bop": Body(65_000, 544_507.43, 2.4868349e9, 25_000, 1_221_060.9),
    "pol": Body(44_000, 901_902.62, 7.2170208e8, 5_000, 1_042_138.9),

    "eeloo": Body(210_000, 19_460, 7.4410815e10, 5_000, 1.1908294e8)
}


@dataclass
class Scanner:
    fov: float
    altitude_min: float
    altitude_best: float
    altitude_max: float


@dataclass
class SolutionParams:
    p: int
    q: int
    semi_major_axis: float
    eccentricity_min: float
    eccentricity_max: float


FOV_MAX = 20  # fov capped in SCANSat to 20° after scaling


def coprimes_of(n: int, start: int = 1, end: int = inf) -> Iterator[int]:
    k = start
    while k <= end:
        if gcd(n, k) == 1:
            yield k
        k += 1


def get_scaled_fov_and_altitude(scanner: Scanner, body: Body)\
        -> tuple[float, float]:
    fov = scanner.fov
    alt = scanner.altitude_best

    r = body.radius
    r_kerbin = BODIES["kerbin"].radius

    if r < r_kerbin:  # fov ony scales for bodies smaller than kerbin
        fov *= sqrt(r_kerbin / r)

    if fov > FOV_MAX:
        alt *= FOV_MAX / fov  # lower altitude to where fov = FOV_MAX
        fov = FOV_MAX

    return fov, alt


class Solver:
    def __init__(self, scanner: Scanner, body: Body):
        self.__scanner: Scanner = scanner
        self.__body: Body = body

        fov, fov_alt = get_scaled_fov_and_altitude(scanner, body)
        self.fov: float = fov
        self.fov_alt: float = fov_alt
        self.k: float = 180 * self.fov_alt / self.fov

    def get_sma(self, p: int, q: int) -> float:
        """
        Finds the semi-major axis required for an orbit with period (p/q)T
        where T is the sidereal rotation period of the body being orbited.
        """
        return (p/q)**(2/3) * self.__body.geo_radius

# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-= EQUATION STUFF =-=-=-=-=-=-=-=-=-=-=-=-=-=-= #

    def _s(self, p: float, q: float, x: float, y: float) -> float:
        """S component of inequality (some rearrangement done)"""
        return sqrt(q**2 * (1-x*y)**4 + p**2 * (1-y*y)**3)

    def _ds_dx(self, p: int, q: int, x: float, y: float) -> float:
        """partial derivative of S with respect to x"""
        s = self._s(p, q, x, y)
        return -2 * (q**2 * y * (1-x*y)**3) / s

    def _ds_dy(self, p: int, q: int, x: float, y: float):
        """partial derivative of S with respect to y"""
        s = self._s(p, q, x, y)
        return -(2 * q**2 * x * (1-x*y)**3 + 3 * p**2 * y * (1-y*y)**2) / s

    def _f(self, p: int, q: int, x: float, y: float) -> float:
        """F component of inequality (some rearrangement done)"""
        return (1-y*y)*self.get_sma(p, q) - (1-x*y)*self.__body.radius

    def _df_dx(self, p: int, q: int, x: float, y: float) -> float:
        """partial derivative of F with respect to x"""
        return self.__body.radius * y

    def _df_dy(self, p: int, q: int, x: float, y: float) -> float:
        """partial derivative of F with respect to y"""
        return x*self.__body.radius - 2*y*self.get_sma(p, q)

    def _m(self, p: int, q: int, x: float, y: float) -> float:
        """M component of inequality (some rearrangement done)"""
        return self.k * x * (1 - x*y) ** 3

    def _dm_dx(self, p: int, q: int, x: float, y: float) -> float:
        """partial derivative of M with respect to x"""
        return self.k * (1 - 4*x*y) * (1 - x*y) ** 2

    def _dm_dy(self, p: int, q: int, x: float, y: float) -> float:
        """partial derivative of M with respect to y"""
        return -3 * self.k * x**2 * (1 - x*y)**2

    def _inequality_value(self, p: int, q: int, x: float, y: float) -> float:
        """Calculates difference between the two sides of the inequality"""

        s = self._s(p, q, x, y)
        f = self._f(p, q, x, y)
        m = self._m(p, q, x, y)

        return s*f - m

    def _inequality_d_dx(self, p: int, q: int, x: float, y: float) -> float:
        """gradient of inequality in x direction"""
        s = self._s(p, q, x, y)
        ds_dx = self._ds_dx(p, q, x, y)

        f = self._f(p, q, x, y)
        df_dx = self._df_dx(p, q, x, y)

        dm_dx = self._dm_dx(p, q, x, y)

        return s*df_dx + f*ds_dx - dm_dx

    def _inequality_d_dy(self, p: int, q: int, x: float, y: float) -> float:
        """gradient of inequality in y direction"""
        s = self._s(p, q, x, y)
        ds_dy = self._ds_dy(p, q, x, y)

        f = self._f(p, q, x, y)
        df_dy = self._df_dy(p, q, x, y)

        dm_dy = self._dm_dy(p, q, x, y)

        return s*df_dy + f*ds_dy - dm_dy

    def _fixed_track_value(self, p: int, q: int, x: float, y: float) -> float:
        """
        Variant of inequality with fov fixed at max. Ensures coverage above
        'best altitude' of scanner as other inequality will over scale.
        """
        s = self._s(p, q, x, y)
        m = self._m(p, q, x, y) / self.fov_alt  # no altitude scaling
        return s - m

    def _fixed_track_d_dx(self, p: int, q: int, x: float, y: float) -> float:
        """x gradient of alternative inequality"""
        ds_dx = self._ds_dx(p, q, x, y)
        dm_dx = self._dm_dx(p, q, x, y) / self.fov_alt  # no altitude scaling

        return ds_dx - dm_dx

    def _fixed_track_d_dy(self, p: int, q: int, x: float, y: float) -> float:
        """y gradient of alternative inequality"""
        ds_dy = self._ds_dy(p, q, x, y)
        dm_dy = self._dm_dy(p, q, x, y) / self.fov_alt  # no altitude scaling

        return ds_dy - dm_dy

# -=-=-=-=-=-=-=-=-=-=-=-=--=-=- SOLVER STUFF -=-=-=-=-=-=-=-=-=-=-=-=--=-=-= #
