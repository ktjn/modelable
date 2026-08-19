#nullable enable
using System;
using System.Collections.Generic;

namespace Modelable.Catalog;

public sealed record CatalogProductV1
{
    public required Guid ProductId { get; init; }
    public required string Name { get; init; }
}
