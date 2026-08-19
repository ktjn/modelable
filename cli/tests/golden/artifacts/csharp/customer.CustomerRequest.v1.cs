#nullable enable
using System;
using System.Collections.Generic;

namespace Modelable.Customer;

public sealed record CustomerCustomerRequestV1
{
    public required Guid CustomerId { get; init; }
    public required string DisplayName { get; init; }
    public required string Email { get; init; }
    public required string Status { get; init; }
    public required List<string> Tags { get; init; }
    public required Dictionary<string, int> Metadata { get; init; }
    public CustomerCustomerRequestV1Address? Address { get; init; }
    public string? FavoriteProduct { get; init; }
}

public sealed record CustomerCustomerRequestV1Address
{
    public required string Line1 { get; init; }
    public string? Line2 { get; init; }
}
