---------------------------- MODULE CompilationProtocol ----------------------------
(* Bounded abstraction of the observed compilation promotion protocol.
   Sources: cli/src/modelable/operations/compilation.py (execute_direct, apply,
   _verify_freshness), file_transaction.py (workspace lock, per-file promotion,
   compensation) and registry/ids.py (ledger lock). Two processes: "d" runs a
   direct compilation, "a" applies a previously previewed compilation.

   Abstractions (assumptions, not code facts):
   - Two destination files stand for the ledger and artifact destinations; a
     file is a version number.
   - The registry-ID and enum-number ledger locks are one ordered pair. Apply
     takes only the ID lock (compilation.py apply); direct takes ID then enum.
   - Apply's freshness check runs once under the ID lock and again under the
     workspace lock (validate callback); both compare every destination with
     the preview snapshot.
   - A process crash releases its locks (stale-lock reclamation by PID
     liveness is assumed to complete) and leaves promoted files in place: the
     implementation has no commit journal.
   - Rollback restores the previous version of every promoted file; when
     RollbackMayFail it may skip a file.
   Not modeled: staging, hashes, permissions, audit file, cleanup errors,
   timeouts, more than two processes, PID reuse. *)
EXTENDS Naturals, FiniteSets

CONSTANTS RollbackMayFail, CanCrash

Procs == {"d", "a"}
Files == {1, 2}
NoOne == "none"
Terminal == {"committed", "rolledBack", "rejected", "crashed"}

VARIABLES pc, idLock, enumLock, wsLock, disk, base, todo, done, rbFailed

vars == <<pc, idLock, enumLock, wsLock, disk, base, todo, done, rbFailed>>

Init ==
  /\ pc = [p \in Procs |-> "start"]
  /\ idLock = NoOne /\ enumLock = NoOne /\ wsLock = NoOne
  /\ disk = [f \in Files |-> 0]
  /\ base = [p \in Procs |-> [f \in Files |-> 0]]
  /\ todo = [p \in Procs |-> {}]
  /\ done = [p \in Procs |-> {}]
  /\ rbFailed = FALSE

Release(p) ==
  /\ idLock' = IF idLock = p THEN NoOne ELSE idLock
  /\ enumLock' = IF enumLock = p THEN NoOne ELSE enumLock
  /\ wsLock' = IF wsLock = p THEN NoOne ELSE wsLock

SetPc(p, v) == pc' = [pc EXCEPT ![p] = v]

\* ---- direct compilation: ID lock, enum lock, workspace lock ----
DAcqId == pc["d"] = "start" /\ idLock = NoOne
  /\ idLock' = "d" /\ SetPc("d", "hasId")
  /\ UNCHANGED <<enumLock, wsLock, disk, base, todo, done, rbFailed>>
DAcqEnum == pc["d"] = "hasId" /\ enumLock = NoOne
  /\ enumLock' = "d" /\ SetPc("d", "hasBoth")
  /\ base' = [base EXCEPT !["d"] = disk]   \* reads current state under both ledger locks
  /\ UNCHANGED <<idLock, wsLock, disk, todo, done, rbFailed>>
DAcqWs == pc["d"] = "hasBoth" /\ wsLock = NoOne
  /\ wsLock' = "d" /\ SetPc("d", "promote")
  /\ todo' = [todo EXCEPT !["d"] = Files] /\ done' = [done EXCEPT !["d"] = {}]
  /\ UNCHANGED <<idLock, enumLock, disk, base, rbFailed>>

\* ---- apply: ID lock, freshness check, workspace lock, freshness check ----
AAcqId == pc["a"] = "start" /\ idLock = NoOne
  /\ idLock' = "a" /\ SetPc("a", "hasId")
  /\ UNCHANGED <<enumLock, wsLock, disk, base, todo, done, rbFailed>>
ACheck1 == pc["a"] = "hasId"
  /\ (IF disk = base["a"]
        THEN SetPc("a", "fresh1") /\ UNCHANGED <<idLock, enumLock, wsLock>>
        ELSE SetPc("a", "rejected") /\ Release("a"))
  /\ UNCHANGED <<disk, base, todo, done, rbFailed>>
AAcqWs == pc["a"] = "fresh1" /\ wsLock = NoOne
  /\ wsLock' = "a" /\ SetPc("a", "fresh2")
  /\ UNCHANGED <<idLock, enumLock, disk, base, todo, done, rbFailed>>
ACheck2 == pc["a"] = "fresh2"
  /\ (IF disk = base["a"]
        THEN /\ SetPc("a", "promote") /\ UNCHANGED <<idLock, enumLock, wsLock>>
             /\ todo' = [todo EXCEPT !["a"] = Files] /\ done' = [done EXCEPT !["a"] = {}]
        ELSE /\ SetPc("a", "rejected") /\ Release("a") /\ UNCHANGED <<todo, done>>)
  /\ UNCHANGED <<disk, base, rbFailed>>

\* ---- promotion, failure, compensation (shared) ----
Promote(p) == pc[p] = "promote" /\ todo[p] # {}
  /\ \E f \in todo[p] :
       /\ disk' = [disk EXCEPT ![f] = base[p][f] + 1]
       /\ todo' = [todo EXCEPT ![p] = @ \ {f}]
       /\ done' = [done EXCEPT ![p] = @ \cup {f}]
  /\ UNCHANGED <<pc, idLock, enumLock, wsLock, base, rbFailed>>
Commit(p) == pc[p] = "promote" /\ todo[p] = {}
  /\ SetPc(p, "committed") /\ Release(p)
  /\ UNCHANGED <<disk, base, todo, done, rbFailed>>
Fail(p) == pc[p] = "promote" /\ todo[p] # {}      \* a failure_mode raised before the last file
  /\ SetPc(p, "rollback")
  /\ UNCHANGED <<idLock, enumLock, wsLock, disk, base, todo, done, rbFailed>>
Rollback(p) == pc[p] = "rollback" /\ done[p] # {}
  /\ \E f \in done[p] :
       /\ done' = [done EXCEPT ![p] = @ \ {f}]
       /\ IF RollbackMayFail
            THEN \/ (disk' = [disk EXCEPT ![f] = base[p][f]] /\ UNCHANGED rbFailed)
                 \/ (UNCHANGED disk /\ rbFailed' = TRUE)
            ELSE disk' = [disk EXCEPT ![f] = base[p][f]] /\ UNCHANGED rbFailed
  /\ UNCHANGED <<pc, idLock, enumLock, wsLock, base, todo>>
RolledBack(p) == pc[p] = "rollback" /\ done[p] = {}
  /\ SetPc(p, "rolledBack") /\ Release(p)
  /\ UNCHANGED <<disk, base, todo, done, rbFailed>>
Crash(p) == CanCrash /\ pc[p] = "promote"
  /\ SetPc(p, "crashed") /\ Release(p)
  /\ UNCHANGED <<disk, base, todo, done, rbFailed>>

Terminated == /\ \A p \in Procs : pc[p] \in Terminal
  /\ UNCHANGED vars

Next ==
  \/ DAcqId \/ DAcqEnum \/ DAcqWs \/ AAcqId \/ ACheck1 \/ AAcqWs \/ ACheck2
  \/ \E p \in Procs : Promote(p) \/ Commit(p) \/ Fail(p) \/ Rollback(p) \/ RolledBack(p) \/ Crash(p)
  \/ Terminated

Spec == Init /\ [][Next]_vars

\* ---- properties, one per contract clause ----
\* Workspace promotion is exclusive (file_transaction workspace lock).
PromotionExclusive == Cardinality({p \in Procs : pc[p] \in {"promote", "rollback"}}) <= 1
\* Lock holders are always live, non-terminated processes unless crashed processes released them.
LocksHeldByActive ==
  \A l \in {idLock, enumLock, wsLock} : l = NoOne \/ pc[l] \notin Terminal
Quiescent == \A p \in Procs : pc[p] \notin {"promote", "rollback"}
Faulted == rbFailed \/ (\E p \in Procs : pc[p] = "crashed")
CommitCount == Cardinality({p \in Procs : pc[p] = "committed"})
\* Without crashes or failed compensation, files move together and no committed update is lost.
FilesConsistent == Quiescent => disk[1] = disk[2]
NoLostUpdate == (Quiescent /\ ~Faulted) => (disk[1] = CommitCount /\ disk[2] = CommitCount)
==================================================================================
