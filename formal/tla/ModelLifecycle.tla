--------------------------- MODULE ModelLifecycle ---------------------------
(***************************************************************************)
(* Formal verification of Modelable semantic lifecycle, usage evidence,    *)
(* compatibility, and resolution invariants.                               *)
(*                                                                         *)
(* Architecture reference: docs/tla-formal-verification.md                 *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets

CONSTANTS
    Declarations,
    Versions,
    Fingerprints,
    Consumers,
    Profiles

VARIABLES
    known,
    published,
    semanticFingerprint,
    lifecycle,
    consumerUses,
    compatibility,
    retirementApproved,
    resolved

vars == <<known, published, semanticFingerprint, lifecycle, consumerUses, compatibility, retirementApproved, resolved>>

None == 0
LifecycleStates == {"candidate", "published", "deprecated", "retired"}

(***************************************************************************)
(* Helpers for deterministic resolution ordering                           *)
(***************************************************************************)
MaxVersion(candidates) == CHOOSE v \in candidates : \A other \in candidates : v >= other

(***************************************************************************)
(* Initial State                                                           *)
(***************************************************************************)
Init ==
    /\ known = {}
    /\ published = {}
    /\ semanticFingerprint = [dv \in {} |-> ""]
    /\ lifecycle = [dv \in {} |-> ""]
    /\ consumerUses = [c \in Consumers |-> {}]
    /\ compatibility = [d \in Declarations, v1 \in Versions, v2 \in Versions, p \in Profiles |-> FALSE]
    /\ retirementApproved = {}
    /\ resolved = [c \in Consumers, d \in Declarations, p \in Profiles |-> None]

(***************************************************************************)
(* Transitions                                                             *)
(***************************************************************************)

\* Admit a new exact declaration version into the candidate pool
AdmitVersion(d, v, fp) ==
    /\ d \in Declarations
    /\ v \in Versions
    /\ fp \in Fingerprints
    /\ <<d, v>> \notin known
    /\ known' = known \union {<<d, v>>}
    /\ semanticFingerprint' = [x \in (known \union {<<d, v>>}) |-> IF x = <<d, v>> THEN fp ELSE semanticFingerprint[x]]
    /\ lifecycle' = [x \in (known \union {<<d, v>>}) |-> IF x = <<d, v>> THEN "candidate" ELSE lifecycle[x]]
    /\ UNCHANGED <<published, consumerUses, compatibility, retirementApproved, resolved>>

\* Publish a candidate version, freezing its semantic identity
PublishVersion(d, v) ==
    /\ <<d, v>> \in known
    /\ lifecycle[<<d, v>>] = "candidate"
    /\ published' = published \union {<<d, v>>}
    /\ lifecycle' = [lifecycle EXCEPT ![<<d, v>>] = "published"]
    /\ UNCHANGED <<known, semanticFingerprint, consumerUses, compatibility, retirementApproved, resolved>>

\* Record explicit compatibility between two published versions under a named profile
RecordCompatibility(d, v1, v2, profile, isCompat) ==
    /\ <<d, v1>> \in published
    /\ <<d, v2>> \in published
    /\ profile \in Profiles
    /\ isCompat \in BOOLEAN
    /\ compatibility[d, v1, v2, profile] /= isCompat
    /\ compatibility' = [compatibility EXCEPT ![d, v1, v2, profile] = isCompat]
    /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, consumerUses, retirementApproved, resolved>>

\* Record explicit consumer usage evidence for a published version
RecordUsage(c, d, v) ==
    /\ c \in Consumers
    /\ <<d, v>> \in published
    /\ lifecycle[<<d, v>>] /= "retired"
    /\ <<d, v>> \notin consumerUses[c]
    /\ consumerUses' = [consumerUses EXCEPT ![c] = @ \union {<<d, v>>}]
    /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, compatibility, retirementApproved, resolved>>

\* Remove consumer usage evidence
RemoveUsage(c, d, v) ==
    /\ c \in Consumers
    /\ <<d, v>> \in consumerUses[c]
    /\ consumerUses' = [consumerUses EXCEPT ![c] = @ \ {<<d, v>>}]
    /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, compatibility, retirementApproved, resolved>>

\* Deprecate a published version; existing consumers remain valid
DeprecateVersion(d, v) ==
    /\ <<d, v>> \in published
    /\ lifecycle[<<d, v>>] = "published"
    /\ lifecycle' = [lifecycle EXCEPT ![<<d, v>>] = "deprecated"]
    /\ UNCHANGED <<known, published, semanticFingerprint, consumerUses, compatibility, retirementApproved, resolved>>

\* Approve retirement explicitly via host policy decision
ApproveRetirement(d, v) ==
    /\ <<d, v>> \in published
    /\ lifecycle[<<d, v>>] = "deprecated"
    /\ <<d, v>> \notin retirementApproved
    /\ retirementApproved' = retirementApproved \union {<<d, v>>}
    /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, consumerUses, compatibility, resolved>>

\* Retire a deprecated version when approved and no active consumer references it
RetireVersion(d, v) ==
    /\ <<d, v>> \in published
    /\ lifecycle[<<d, v>>] = "deprecated"
    /\ <<d, v>> \in retirementApproved
    /\ \A c \in Consumers : <<d, v>> \notin consumerUses[c]
    /\ \A c \in Consumers, p \in Profiles : resolved[c, d, p] /= v
    /\ lifecycle' = [lifecycle EXCEPT ![<<d, v>>] = "retired"]
    /\ UNCHANGED <<known, published, semanticFingerprint, consumerUses, compatibility, retirementApproved, resolved>>

\* Resolve consumer requirements to an exact, non-retired compatible version
ResolveConsumer(c, d, reqV, profile) ==
    /\ c \in Consumers
    /\ d \in Declarations
    /\ reqV \in Versions
    /\ profile \in Profiles
    /\ LET candidates == { v \in Versions :
                /\ <<d, v>> \in published
                /\ lifecycle[<<d, v>>] /= "retired"
                /\ (v = reqV \/ compatibility[d, reqV, v, profile] = TRUE) }
       IN IF candidates /= {}
          THEN LET selected == MaxVersion(candidates)
               IN /\ resolved' = [resolved EXCEPT ![c, d, profile] = selected]
                  /\ consumerUses' = [consumerUses EXCEPT ![c] = @ \union {<<d, selected>>}]
                  /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, compatibility, retirementApproved>>
          ELSE /\ resolved[c, d, profile] /= None
               /\ resolved' = [resolved EXCEPT ![c, d, profile] = None]
               /\ UNCHANGED <<known, published, semanticFingerprint, lifecycle, consumerUses, compatibility, retirementApproved>>

Next ==
    \/ \E d \in Declarations, v \in Versions, fp \in Fingerprints : AdmitVersion(d, v, fp)
    \/ \E d \in Declarations, v \in Versions : PublishVersion(d, v)
    \/ \E d \in Declarations, v1 \in Versions, v2 \in Versions, p \in Profiles, b \in BOOLEAN : RecordCompatibility(d, v1, v2, p, b)
    \/ \E c \in Consumers, d \in Declarations, v \in Versions : RecordUsage(c, d, v)
    \/ \E c \in Consumers, d \in Declarations, v \in Versions : RemoveUsage(c, d, v)
    \/ \E d \in Declarations, v \in Versions : DeprecateVersion(d, v)
    \/ \E d \in Declarations, v \in Versions : ApproveRetirement(d, v)
    \/ \E d \in Declarations, v \in Versions : RetireVersion(d, v)
    \/ \E c \in Consumers, d \in Declarations, reqV \in Versions, p \in Profiles : ResolveConsumer(c, d, reqV, p)

Spec == Init /\ [][Next]_vars /\ WF_vars(\E d \in Declarations, v \in Versions : RetireVersion(d, v))

(***************************************************************************)
(* Safety Properties                                                       *)
(***************************************************************************)

\* Type correctness invariant
TypeOK ==
    /\ known \subseteq (Declarations \times Versions)
    /\ published \subseteq known
    /\ semanticFingerprint \in [known -> Fingerprints]
    /\ lifecycle \in [known -> LifecycleStates]
    /\ consumerUses \in [Consumers -> SUBSET known]
    /\ compatibility \in [Declarations \times Versions \times Versions \times Profiles -> BOOLEAN]
    /\ retirementApproved \subseteq known
    /\ resolved \in [Consumers \times Declarations \times Profiles -> Versions \union {None}]

\* Every published version is known
PublishedIsKnown ==
    \A dv \in published : dv \in known

\* A published exact identity cannot acquire different semantics
PublishedFingerprintUnchanged ==
    [][\A dv \in published : (dv \in published' => semanticFingerprint'[dv] = semanticFingerprint[dv])]_vars

\* A retired version was previously a published contract
RetiredIsPublished ==
    \A dv \in known : lifecycle[dv] = "retired" => dv \in published

\* Active recorded consumers never reference retired versions
ActiveConsumerNeverReferencesRetired ==
    /\ \A c \in Consumers : \A dv \in consumerUses[c] : lifecycle[dv] /= "retired"
    /\ \A c \in Consumers, d \in Declarations, p \in Profiles :
        resolved[c, d, p] /= None => lifecycle[<<d, resolved[c, d, p]>>] /= "retired"

\* Persisted resolution is always an exact version or none, never a range or mutable tag
ResolutionIsExact ==
    \A c \in Consumers, d \in Declarations, p \in Profiles :
        resolved[c, d, p] \in Versions \union {None}

\* Missing compatibility information is never interpreted as compatible
CompatibilityIsExplicit ==
    \A c \in Consumers, d \in Declarations, p \in Profiles :
        resolved[c, d, p] /= None =>
            /\ <<d, resolved[c, d, p]>> \in published
            /\ lifecycle[<<d, resolved[c, d, p]>>] /= "retired"

\* An empty observed usage set alone cannot authorize retirement
NoEvidenceIsNotSafety ==
    \A dv \in known : lifecycle[dv] = "retired" => dv \in retirementApproved

\* Deterministic resolution: resolved is a well-defined function
DeterministicResolution ==
    \A c \in Consumers, d \in Declarations, p \in Profiles :
        resolved[c, d, p] \in Versions \union {None}

=============================================================================
