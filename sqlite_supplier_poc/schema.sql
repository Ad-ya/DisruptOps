PRAGMA foreign_keys = ON;

CREATE TABLE materials (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL,
    specification TEXT NOT NULL, safety_stock INTEGER NOT NULL CHECK(safety_stock >= 0)
);
CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE suppliers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, approved INTEGER NOT NULL CHECK(approved IN (0,1))
);
CREATE TABLE bom (
    product_id TEXT REFERENCES products(id), material_id TEXT REFERENCES materials(id),
    quantity_per_product INTEGER NOT NULL CHECK(quantity_per_product > 0),
    PRIMARY KEY(product_id, material_id)
);
CREATE TABLE production_orders (
    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
    ordered_quantity INTEGER NOT NULL CHECK(ordered_quantity > 0),
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled'))
);
CREATE TABLE production_schedule (
    order_id TEXT REFERENCES production_orders(id), day TEXT NOT NULL,
    planned_quantity INTEGER NOT NULL CHECK(planned_quantity >= 0),
    completed_quantity INTEGER NOT NULL DEFAULT 0
        CHECK(completed_quantity >= 0 AND completed_quantity <= planned_quantity),
    PRIMARY KEY(order_id, day)
);
CREATE TABLE inventory (
    material_id TEXT PRIMARY KEY REFERENCES materials(id),
    usable_quantity INTEGER NOT NULL CHECK(usable_quantity >= 0), as_of TEXT NOT NULL
);
CREATE TABLE shipments (
    id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    material_id TEXT NOT NULL REFERENCES materials(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0), promised_date TEXT NOT NULL,
    revised_date TEXT, actual_date TEXT, accepted_quantity INTEGER,
    status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
    CHECK(status != 'delivered' OR
          (actual_date IS NOT NULL AND accepted_quantity IS NOT NULL AND accepted_quantity >= 0))
);
