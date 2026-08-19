#nullable enable
using System;
using System.Collections.Generic;

namespace Modelable.Customer;

public sealed record CustomerCustomerDbV1
{
    public required Guid CustomerId { get; init; }
    public required string DisplayName { get; init; }
    public required string Email { get; init; }
    public string? InternalRiskNotes { get; init; }
    public required string Status { get; init; }
    public required List<string> Tags { get; init; }
    public required Dictionary<string, int> Metadata { get; init; }
    public CustomerCustomerDbV1Address? Address { get; init; }
    public string? FavoriteProduct { get; init; }
    public required DateTime CreatedAt { get; init; }
    public DateTime? UpdatedAt { get; init; }
}

public sealed record CustomerCustomerDbV1Address
{
    public required string Line1 { get; init; }
    public string? Line2 { get; init; }
}
