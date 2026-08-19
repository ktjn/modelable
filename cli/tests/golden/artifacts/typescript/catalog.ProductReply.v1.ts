/**
 * @modelable domain: catalog
 * @modelable name: ProductReply
 * @modelable owner: catalog-team
 * @modelable kind: projection
 * @modelable version: 1
 * @modelable source: catalog.Product@1
 */
export interface CatalogProductReplyV1 {
  productId: string;
  name: string;
}
export type ProductReply = CatalogProductReplyV1;
