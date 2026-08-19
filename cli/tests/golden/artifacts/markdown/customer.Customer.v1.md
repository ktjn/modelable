# Customer v1

**Domain:** customer  
**Name:** Customer  
**Version:** 1  
**Artifact ID:** customer.Customer.v1  
**Artifact:** customer.Customer.v1.md  
**Owner:** customer-team  
**Kind:** entity  
**Change kind:** additive  

## Fields

| Field | Type | Required | Default | Annotations | Classification |
|---|---|---|---|---|---|
| customerId | uuid | yes | — | @key | — |
| displayName | string | yes | — | — | — |
| email | string | yes | — | @pii | — |
| internalRiskNotes | string | no | — | — | secret |
| status | enum(active, suspended, deleted) | yes | — | — | — |
| tags | array<string> | yes | — | — | — |
| metadata | map<string,int> | yes | — | — | — |
| address | object | no | — | — | — |
| favoriteProduct | ref<catalog.Product> | no | — | — | — |
| createdAt | timestamp | yes | — | @server | — |
| updatedAt | timestamp | no | — | @server | — |
