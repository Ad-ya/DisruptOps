from abc import ABC, abstractmethod


class BaseSupplierClient(ABC):
    @abstractmethod
    def get_supplier_update(self, shipment_id: str) -> dict:
        """Fetch one shipment's current supplier notice."""

    @abstractmethod
    def get_alternative_offers(self, material_id: str) -> dict:
        """Fetch replacement offers for a material."""
