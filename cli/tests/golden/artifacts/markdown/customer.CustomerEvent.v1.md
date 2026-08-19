# CustomerEvent v1

**Domain:** customer  
**Name:** CustomerEvent  
**Version:** 1  
**Artifact ID:** customer.CustomerEvent.v1  
**Artifact:** customer.CustomerEvent.v1.md  
**Owner:** customer-team  
**Kind:** projection  
**Auto generated:** yes  
**Source:** customer.Customer @ 1 as customer  

## Sources

| Model | Version | Alias |
|---|---|---|
| customer.Customer | 1 | customer |

## Fields

| Field | Lineage | Annotations | Classification |
|---|---|---|---|
| customerId | direct: customer.customerId (customer.Customer) | — | — |
| displayName | direct: customer.displayName (customer.Customer) | — | — |
| email | direct: customer.email (customer.Customer) | @pii | — |
| internalRiskNotes | direct: customer.internalRiskNotes (customer.Customer) | — | secret |
| status | direct: customer.status (customer.Customer) | — | — |
| tags | direct: customer.tags (customer.Customer) | — | — |
| metadata | direct: customer.metadata (customer.Customer) | — | — |
| address | direct: customer.address (customer.Customer) | — | — |
| favoriteProduct | direct: customer.favoriteProduct (customer.Customer) | — | — |
| createdAt | direct: customer.createdAt (customer.Customer) | @server | — |
| updatedAt | direct: customer.updatedAt (customer.Customer) | @server | — |
