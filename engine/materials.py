"""Material constants and bar data."""
import math

ES = 2.04e6          # ksc
ECU = 0.003
BAR_AREA = {s: math.pi * (s / 10) ** 2 / 4 for s in (10, 12, 16, 20, 25, 28, 32)}   # cm2
STD_FC = [210, 240, 280, 320, 350, 400, 450, 500, 560, 600, 650, 700]


def beta1(fc):
    """ACI 318-19 Table 22.2.2.4.3 (ksc form)."""
    if fc <= 280:
        return 0.85
    return max(0.65, 0.85 - 0.05 * (fc - 280) / 70.0)


def Ec(fc):
    """ACI 318-19 19.2.2.1 (normal weight), 15100*sqrt(f'c) ksc."""
    return 15100.0 * math.sqrt(fc)


def fyt_shear(tie_db, fyt):
    """CEDA practice: DB12 4000 ksc, DB16-32 <= 4200 ksc."""
    return min(fyt, 4000.0) if tie_db <= 12 else min(fyt, 4200.0)
