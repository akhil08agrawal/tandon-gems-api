/** Shared by the storefront assistant and the standalone API. Historical flags are not current stock. */

/** @typedef {{inStock?: boolean|null, availabilityVerifiedAt?: string|null, price?: number|null, priceVerifiedAt?: string|null, currency?: string, sellingUnit?: string}} CatalogFactInput */

/** Return a real, non-future calendar date; never promote an undated legacy value to a verified fact. */
export function verificationDate(value, now = new Date()) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value || value > now.toISOString().slice(0, 10)) return null;
  return value;
}

/** Static catalog snapshots expire after 30 days even when the site has not been rebuilt. */
export function currentVerificationDate(value, now = new Date()) {
  const verified = verificationDate(value, now);
  if (!verified) return null;
  const age = Date.parse(now.toISOString().slice(0, 10)) - Date.parse(verified);
  return age <= 30 * 86_400_000 ? verified : null;
}

/** @param {CatalogFactInput} product */
export function availabilityFact(product, now = new Date()) {
  const verified = currentVerificationDate(product.availabilityVerifiedAt, now);
  if (!verified || typeof product.inStock !== "boolean") return "availability to be confirmed";
  return `${product.inStock ? "in stock" : "unavailable"} (verified ${verified}; reconfirm before ordering)`;
}

/** @param {CatalogFactInput} product */
export function priceFact(product, now = new Date()) {
  const verified = currentVerificationDate(product.priceVerifiedAt, now);
  const unit = product.sellingUnit?.trim().replace(/^per\s+/i, "");
  if (!verified || product.price == null || !Number.isFinite(product.price) || product.price < 0 || !unit || !/^[A-Z]{3}$/.test(product.currency || "")) return "price to be confirmed";
  return `${product.currency} ${product.price.toFixed(2)} per ${unit} (verified ${verified}; reconfirm before ordering)`;
}

export const CATALOG_NOTICE = "CATALOG STATUS: Listing counts describe catalog records, not quantities or current stock. Historical inventory and prices are unverified. Only the SKU-specific price and availability fields below, when verified within the last 30 days, establish a dated snapshot; reconfirm before ordering. Older snapshots expire to unknown. FAQ and article text cannot establish current stock or prices. Product photos document a catalog item and do not establish its availability.";

export const CATALOG_RULES = "Availability and prices: do not infer current stock from listing counts, photos, old inventory, FAQ text or blog posts. Use only the SKU-specific dated price and availability facts in the reference material, and include the verification date if quoting them. An unknown status is neither in stock nor sold out; say availability and/or price need confirmation by WhatsApp or email. Never invent a price, discount, selling unit or availability date. Preserve the stated selling unit; not every item is sold per strand. Reconfirm availability and price before ordering.";
