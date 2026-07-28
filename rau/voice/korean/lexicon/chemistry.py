"""Element symbols and formulas, keyed by their written form rather than a word.

Unlike every other lexicon module these keys are case-sensitive: ``Co`` is
cobalt and ``CO`` is carbon monoxide. The engine looks them up only inside
formula-shaped tokens, so an ordinary ``I`` or ``In`` in running text is never
turned into iodine or indium.
"""
from __future__ import annotations

from typing import Dict

#: Symbol -> the Korean name a news anchor would say. Several are native Korean
#: words rather than transliterations (철, 금, 은, 납, 구리, 백금, 수은).
ELEMENTS: Dict[str, str] = {
    "H": "수소", "He": "헬륨", "Li": "리튬", "Be": "베릴륨", "B": "붕소",
    "C": "탄소", "N": "질소", "O": "산소", "F": "플루오린", "Ne": "네온",
    "Na": "나트륨", "Mg": "마그네슘", "Al": "알루미늄", "Si": "규소", "P": "인",
    "S": "황", "Cl": "염소", "Ar": "아르곤", "K": "칼륨", "Ca": "칼슘",
    "Sc": "스칸듐", "Ti": "티타늄", "V": "바나듐", "Cr": "크로뮴", "Mn": "망간",
    "Fe": "철", "Co": "코발트", "Ni": "니켈", "Cu": "구리", "Zn": "아연",
    "Ga": "갈륨", "Ge": "게르마늄", "As": "비소", "Se": "셀레늄", "Br": "브로민",
    "Kr": "크립톤", "Rb": "루비듐", "Sr": "스트론튬", "Y": "이트륨",
    "Zr": "지르코늄", "Nb": "나이오븀", "Mo": "몰리브덴", "Tc": "테크네튬",
    "Ru": "루테늄", "Rh": "로듐", "Pd": "팔라듐", "Ag": "은", "Cd": "카드뮴",
    "In": "인듐", "Sn": "주석", "Sb": "안티모니", "Te": "텔루륨", "I": "아이오딘",
    "Xe": "제논", "Cs": "세슘", "Ba": "바륨", "La": "란타넘", "Ce": "세륨",
    "Pr": "프라세오디뮴", "Nd": "네오디뮴", "Pm": "프로메튬", "Sm": "사마륨",
    "Eu": "유로퓸", "Gd": "가돌리늄", "Tb": "터븀", "Dy": "디스프로슘",
    "Ho": "홀뮴", "Er": "어븀", "Tm": "툴륨", "Yb": "이터븀", "Lu": "루테튬",
    "Hf": "하프늄", "Ta": "탄탈럼", "W": "텅스텐", "Re": "레늄", "Os": "오스뮴",
    "Ir": "이리듐", "Pt": "백금", "Au": "금", "Hg": "수은", "Tl": "탈륨",
    "Pb": "납", "Bi": "비스무트", "Po": "폴로늄", "At": "아스타틴", "Rn": "라돈",
    "Fr": "프랑슘", "Ra": "라듐", "Ac": "악티늄", "Th": "토륨",
    "Pa": "프로트악티늄", "U": "우라늄", "Np": "넵투늄", "Pu": "플루토늄",
    "Am": "아메리슘", "Cm": "퀴륨", "Bk": "버클륨", "Cf": "캘리포늄",
    "Es": "아인슈타이늄", "Fm": "페르뮴", "Md": "멘델레븀", "No": "노벨륨",
    "Lr": "로렌슘", "Rf": "러더포듐", "Db": "더브늄", "Sg": "시보귬",
    "Bh": "보륨", "Hs": "하슘", "Mt": "마이트너륨", "Ds": "다름슈타튬",
    "Rg": "뢴트게늄", "Cn": "코페르니슘", "Nh": "니호늄", "Fl": "플레로븀",
    "Mc": "모스코븀", "Lv": "리버모륨", "Ts": "테네신", "Og": "오가네손",
}

#: Formulas with a settled Korean name. Reading these symbol by symbol would be
#: technically correct and completely unnatural — nobody says 에이치 투 오.
FORMULAS: Dict[str, str] = {
    "H2": "수소", "N2": "질소", "O2": "산소", "O3": "오존",
    "H2O": "물", "H2O2": "과산화수소", "D2O": "중수",
    "CO": "일산화탄소", "CO2": "이산화탄소", "CH4": "메탄", "C2H6": "에탄",
    "C3H8": "프로판", "C4H10": "부탄", "NH3": "암모니아", "NO": "일산화질소",
    "NO2": "이산화질소", "N2O": "아산화질소", "SO2": "이산화황", "SO3": "삼산화황",
    "NaCl": "염화나트륨", "KCl": "염화칼륨", "CaCl2": "염화칼슘",
    "HCl": "염산", "H2SO4": "황산", "HNO3": "질산", "H3PO4": "인산",
    "H2CO3": "탄산", "CH3COOH": "아세트산", "NaOH": "수산화나트륨",
    "KOH": "수산화칼륨", "Ca(OH)2": "수산화칼슘", "CaCO3": "탄산칼슘",
    "NaHCO3": "탄산수소나트륨", "Na2CO3": "탄산나트륨", "CaO": "산화칼슘",
    "SiO2": "이산화규소", "Fe2O3": "산화철", "Al2O3": "산화알루미늄",
    "TiO2": "이산화티타늄", "ZnO": "산화아연", "MgO": "산화마그네슘",
    "CH3OH": "메탄올", "C2H5OH": "에탄올", "C6H12O6": "포도당",
    "C12H22O11": "설탕", "C6H6": "벤젠", "CH2O": "폼알데하이드",
    "H2S": "황화수소", "HF": "플루오린화수소", "HBr": "브로민화수소",
    "N2H4": "하이드라진", "PVC": "피브이씨",
}

#: Symbols safe to expand when they stand alone. ``Fe는 금속이다`` is iron, but
#: ``In``, ``As``, ``At``, ``No``, ``He``, ``Be``, ``Am`` and every one-letter
#: symbol are ordinary English words far more often than they are elements, so
#: they are left for the normal word path. Excluded for the same reason: ``Al``
#: (Al Gore, Al Jazeera), ``Li`` and ``Mo`` and ``Ra`` (surnames and given
#: names), ``Na`` and ``Ga`` and ``Se`` (syllables of romanised Korean names —
#: ``Se-ri`` must not open with 셀레늄), ``Sr`` (Senior, Señor) and ``Bi``
#: (the ``bi-`` prefix).
BARE_SYMBOLS: Dict[str, str] = {
    symbol: ELEMENTS[symbol]
    for symbol in (
        "Mg", "Si", "Cl", "Ca", "Ti", "Cr", "Mn", "Fe", "Ni", "Cu", "Zn",
        "Br", "Kr", "Rb", "Zr", "Ag", "Cd", "Sn", "Xe", "Cs", "Ba", "Pt",
        "Au", "Hg", "Tl", "Pb", "Rn", "Th", "Pu", "Ne", "Ar", "Ge", "Pd",
        "Ir",
    )
}

__all__ = ["BARE_SYMBOLS", "ELEMENTS", "FORMULAS"]
