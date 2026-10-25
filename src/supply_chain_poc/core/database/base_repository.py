from abc import ABC, abstractmethod


class BaseFactoryRepository(ABC):
    @abstractmethod
    def get_material_context(self, material_id: str) -> dict:
        """Read material, stock and pending shipments."""

    @abstractmethod
    def get_shipment(self, shipment_id: str) -> dict:
        """Read one shipment."""

    @abstractmethod
    def get_requirements(self, material_id: str, start_date: str, days: int = 5) -> dict:
        """Derive material demand from active scheduled production and its BOM."""

    @abstractmethod
    def supplier_history(self, supplier_id: str, material_id: str) -> dict:
        """Summarize recorded delivery outcomes."""

    @abstractmethod
    def get_supplier(self, supplier_id: str) -> dict:
        """Read supplier identity and approval status."""

    @abstractmethod
    def find_past_incidents(self, material_id: str, supplier_id: str, delay_days: int,
                            stock_cover_days: float, as_of: str, planning_days: int = 5) -> dict:
        """Retrieve comparable earlier incidents and their observed action/outcomes."""
