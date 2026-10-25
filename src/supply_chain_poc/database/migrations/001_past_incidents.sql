CREATE TABLE IF NOT EXISTS past_incidents (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id),
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    occurred_on TEXT NOT NULL,
    delay_days INTEGER NOT NULL CHECK(delay_days >= 0),
    stock_cover_days REAL NOT NULL CHECK(stock_cover_days >= 0),
    daily_requirement INTEGER NOT NULL CHECK(daily_requirement > 0),
    planning_days INTEGER NOT NULL CHECK(planning_days BETWEEN 1 AND 30),
    action TEXT NOT NULL CHECK(action IN ('wait','bridge','protect_buffer')),
    replacement_supplier_id TEXT REFERENCES suppliers(id),
    observed_unfulfilled_units INTEGER NOT NULL CHECK(observed_unfulfilled_units >= 0),
    observed_buffer_breach_days INTEGER NOT NULL CHECK(observed_buffer_breach_days >= 0),
    observed_additional_cost_cents INTEGER NOT NULL CHECK(observed_additional_cost_cents >= 0),
    notes TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('synthetic','recorded'))
)
