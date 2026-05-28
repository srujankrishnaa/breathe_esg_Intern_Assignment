"""
SAP OData V2 payload generator.

Produces a fresh, valid OData-style JSON payload on every call.
All generated data passes through the existing normalization pipeline
without flags — plant codes, material groups, units, and quantities
are all within known-good ranges.

Static error files (sap_unknown_plant.json, sap_high_quantity.json)
remain untouched — they are used via the ?file= param in the view.

This generator replaces the static file read as the DEFAULT path
when no ?file= param is present.
"""

import random
import time
from datetime import datetime, timedelta, timezone


# -------------------------------------------------------------------------
# Pools — only values that exist in PlantLookup and SAP_MATERIAL_GROUP_FACTORS
# -------------------------------------------------------------------------
PLANT_POOL = ['1010', '2030', '3050']

# MaterialGroup → (Material code prefix, allowed units)
# CRITICAL: FUEL03 (LPG) MUST only get weight units (KG, TO).
#   Giving it a volume unit triggers a normalization flag because
#   LPG's canonical unit is 'kg', and the normalizer can't convert
#   liters → kg without density data.
#
# NOTE on Material vs MaterialGroup:
#   In real SAP, the Material code (e.g. DSLHSD001) is the primary key —
#   MaterialGroup is derived from it via SAP's material master (T023).
#   We flipped this for the prototype because we don't have SAP's material
#   master data. Here, MaterialGroup drives normalization and the Material
#   code is decorative. The generated codes (MAT-D-247) are stored in
#   RawSAPRecord but never used by the normalizer.
FUEL_POOL = {
    'FUEL01': {'name': 'Diesel',      'material_prefix': 'MAT-D',  'units': ['L', 'GAL']},
    'FUEL02': {'name': 'Petrol',      'material_prefix': 'MAT-P',  'units': ['L', 'GAL']},
    'FUEL03': {'name': 'LPG',         'material_prefix': 'MAT-L',  'units': ['KG', 'TO']},
    'FUEL04': {'name': 'Furnace Oil', 'material_prefix': 'MAT-FO', 'units': ['L', 'GAL']},
}

# Realistic quantity ranges per unit (all below 100k threshold)
QUANTITY_RANGES = {
    'L':   (500, 15000),
    'GAL': (200, 4000),
    'KG':  (300, 8000),
    'TO':  (1, 20),
}

SUPPLIER_POOL = ['SUP-1001', 'SUP-1002', 'SUP-2003', 'SUP-3001']


def _random_sap_date() -> str:
    """
    Generate a random date within the last 6 months, formatted as
    SAP OData V2: /Date(milliseconds)/
    """
    now = datetime.now(tz=timezone.utc)
    days_back = random.randint(1, 180)
    dt = now - timedelta(days=days_back)
    # Zero out time to midnight — SAP dates are typically date-only
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    ms = int(dt.timestamp() * 1000)
    return f"/Date({ms})/"


def _random_po_number() -> str:
    """
    Generate a randomized PO number: '45' + 8 random digits.
    Ensures dedup hash never repeats across calls.
    """
    return '45' + ''.join(str(random.randint(0, 9)) for _ in range(8))


def generate_sap_payload(num_rows: int = 6) -> dict:
    """
    Returns a dict matching SAP OData V2 structure:
    { "value": [ ...items ] }

    Each item has all fields RawSAPRecord expects.
    All generated data passes normalization without flags.

    Args:
        num_rows: Number of line items to generate (default 6)

    Returns:
        dict with "value" key containing list of OData-style records
    """
    items = []

    for i in range(num_rows):
        # Pick random fuel type
        material_group = random.choice(list(FUEL_POOL.keys()))
        fuel_info = FUEL_POOL[material_group]

        # Pick unit from fuel-appropriate set (enforces LPG → weight only)
        unit = random.choice(fuel_info['units'])

        # Generate quantity within realistic range for this unit
        qty_min, qty_max = QUANTITY_RANGES[unit]
        if unit == 'TO':
            # Tonnes: use float with 3 decimals for realism
            quantity = round(random.uniform(qty_min, qty_max), 3)
        else:
            # L/GAL/KG: whole numbers or single decimal
            quantity = round(random.uniform(qty_min, qty_max), 1)

        # Format quantity as SAP does: string with 3 decimal places
        quantity_str = f"{quantity:.3f}"

        # Sequential item number: 00010, 00020, 00030...
        item_number = f"{(i + 1) * 10:05d}"

        # Material code: prefix + sequential number
        material_code = f"{fuel_info['material_prefix']}-{random.randint(100, 999):03d}"

        item = {
            "PurchaseOrder": _random_po_number(),
            "PurchaseOrderItem": item_number,
            "CompanyCode": "IN01",
            "PurchasingOrganization": "PO01",
            "Plant": random.choice(PLANT_POOL),
            "Material": material_code,
            "MaterialGroup": material_group,
            "OrderQuantity": quantity_str,
            "PurchaseOrderQuantityUnit": unit,
            "DocumentDate": _random_sap_date(),
            "Supplier": random.choice(SUPPLIER_POOL),
            "DocumentCurrency": "INR",
        }
        items.append(item)

    return {"value": items}
