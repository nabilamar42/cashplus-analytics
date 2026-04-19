"""Entités métier pures. Aucune dépendance externe."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Coord:
    lat: float
    lon: float


@dataclass(frozen=True)
class Agence:
    code: str
    nom: str
    type: str  # 'Franchisé' | 'Propre'
    ville: str
    coord: Coord
    societe: Optional[str] = None
    dr: Optional[str] = None
    rr: Optional[str] = None
    superviseur: Optional[str] = None
    banque: Optional[str] = None


@dataclass(frozen=True)
class Volume:
    shop_id: str
    cashin_ytd: float
    cashout_ytd: float
    solde_jour: float
    flux_jour: float
    snapshot_date: str  # ISO YYYY-MM-DD

    @property
    def besoin_cash(self) -> float:
        """Déficit net journalier : cash que la propre doit fournir."""
        return max(0.0, -self.solde_jour)


@dataclass(frozen=True)
class Rattachement:
    code_franchise: str
    code_propre: Optional[str]
    distance_km: Optional[float]
    duree_min: Optional[float]
    conforme: bool


Segment = str  # 'HAUTE_VALEUR' | 'STANDARD' | 'MARGINAL' | 'INCONNU'


@dataclass(frozen=True)
class FrancheScored:
    agence: Agence
    volume: Optional[Volume]
    rattachement: Optional[Rattachement]
    segment: Segment
    score: float


@dataclass(frozen=True)
class Company:
    """Franchisé = Société juridique qui possède 1..N shops."""
    societe: str
    banque: Optional[str]
    nb_shops: int
    nb_shops_conformes: int
    nb_shops_nc: int
    nb_villes: int
    dr_principal: Optional[str]
    flux_total_jour: float
    solde_total_jour: float
    besoin_cash_jour: float
    score_acquisition: float = 0.0

    @property
    def conformite_pct(self) -> float:
        return self.nb_shops_conformes / self.nb_shops * 100 if self.nb_shops else 0.0

    @property
    def est_multi_shop(self) -> bool:
        return self.nb_shops > 1


@dataclass
class Scenario:
    nom: str
    propres_ajoutees: list[Agence]
    cree_le: str  # ISO
    notes: str = ""
