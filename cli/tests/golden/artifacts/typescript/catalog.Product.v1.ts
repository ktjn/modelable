/**
 * @modelable domain: catalog
 * @modelable name: Product
 * @modelable owner: catalog-team
 * @modelable kind: entity
 * @modelable version: 1
 * @modelable changeKind: additive
 */
export interface CatalogProductV1 {
  productId: string;
  name: string;
}
export type Product = CatalogProductV1;
