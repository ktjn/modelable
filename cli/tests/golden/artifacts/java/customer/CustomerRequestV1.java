package customer;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

public record CustomerRequestV1(
    UUID customerId,
    String displayName,
    String email,
    String status,
    List<String> tags,
    Map<String, Long> metadata,
    Optional<Address> address,
    Optional<String> favoriteProduct
) {

    public record Address(
        String line1,
        Optional<String> line2
    ) {}
}
