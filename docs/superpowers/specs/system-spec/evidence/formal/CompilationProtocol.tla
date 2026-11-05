---------------------------- MODULE CompilationProtocol ----------------------------
(* Bounded abstraction of the observed compilation promotion protocol.
   Sources: cli/src/modelable/operations/compilation.py (execute_direct, apply,
   _verify_freshness), file_transaction.py (workspace lock, promotion journal,
   per-file promotion, compensation) and registry/ids.py (ledger lock). Two
   processes: "d" runs a direct compilation, "a" applies a previously previewed
   compilation.

   Abstractions (assumptions, not code facts):
   - Two destination files stand for the ledger and artifact destinations; a
     file is a version number.
   - The registry-ID and enum-number ledger locks are one ordered pair. Apply
     takes only the ID lock (compilation.py apply); direct takes ID then enum.
   - Apply's freshness check runs once under the ID lock and again under the
     workspace lock (validate callback); both compare every destination with
     the preview snapshot. The second check runs after journal recovery.
   - A process crash releases its locks (stale-lock reclamation by PID
     liveness is assumed to complete) and leaves promoted files and the
     promotion journal in place.
   - The promotion journal (compilation.journal) records the pre-promotion
     version of every file (the backups). It is written after the workspace
     lock is taken and recovery has run, and removed at the commit point. The
     next holder of the workspace lock restores from a leftover journal before
     doing anything else (Recover).
   - Direct compilation calls FileTransaction.recover() after taking the ID
     and enum locks and before reading the state it stages from (DRecover),
     so it never stages output derived from a half-promoted workspace.
   - Rollback restores the journaled version of every promoted file; when
     RollbackMayFail it may skip a file, and then the journal is kept.
   Not modeled: staging, hashes, permissions, audit file, cleanup errors,
   timeouts, more than two processes, PID reuse, a crash during preparation or
   during recovery itself. *)
EXTENDS Naturals, FiniteSets

CONSTANTS RollbackMayFail, CanCrash

Procs == {"d", "a"}
Files == {1, 2}
NoOne == "none"
Terminal == {"committed", "rolledBack", "rejected", "crashed"}

VARIABLES pc, idLock, enumLock, wsLock, disk, base, todo, done, rbFailed, jrnl, jbase

vars == <<pc, idLock, enumLock, wsLock, disk, base, todo, done, rbFailed, jrnl, jbase>>
jvars == <<jrnl, jbase>>

Init ==
  /\ pc = [p \in Procs |-> "start"]
  /\ idLock = NoOne /\ enumLock = NoOne /\ wsLock = NoOne
  /\ disk = [f \in Files |-> 0]
  /\ base = [p \in Procs |-> [f \in Files |-> 0]]
  /\ todo = [p \in Procs |-> {}]
  /\ done = [p \in Procs |-> {}]
  /\ rbFailed = FALSE
  /\ jrnl = NoOne /\ jbase = [f \in Files |-> 0]

Release(p) ==
  /\ idLock' = IF idLock = p THEN NoOne ELSE idLock
  /\ enumLock' = IF enumLock = p THEN NoOne ELSE enumLock
  /\ wsLock' = IF wsLock = p THEN NoOne ELSE wsLock

SetPc(p, v) == pc' = [pc EXCEPT ![p] = v]

\* ---- direct compilation: ID lock, enum lock, workspace lock ----
DAcqId == pc["d"] = "start" /\ idLock = NoOne
  /\ idLock' = "d" /\ SetPc("d", "hasId")
  /\ UNCHANGED <<enumLock, wsLock, disk, base, todo, done, rbFailed, jvars>>
DAcqEnum == pc["d"] = "hasId" /\ enumLock = NoOne
  /\ enumLock' = "d" /\ SetPc("d", "hasBoth")
  /\ UNCHANGED <<idLock, wsLock, disk, base, todo, done, rbFailed, jvars>>
\* FileTransaction.recover(): take the workspace lock just long enough to roll
\* back a leftover journal, then read the (now consistent) state to stage from.
DRecover == pc["d"] = "hasBoth" /\ wsLock = NoOne
  /\ (IF jrnl # NoOne THEN disk' = jbase ELSE disk' = disk)
  /\ jrnl' = NoOne /\ UNCHANGED jbase
  /\ base' = [base EXCEPT !["d"] = (IF jrnl # NoOne THEN jbase ELSE disk)]
  /\ SetPc("d", "staged")
  /\ UNCHANGED <<idLock, enumLock, wsLock, todo, done, rbFailed>>
DAcqWs == pc["d"] = "staged" /\ wsLock = NoOne
  /\ wsLock' = "d" /\ SetPc("d", "ws")
  /\ UNCHANGED <<idLock, enumLock, disk, base, todo, done, rbFailed, jvars>>

\* ---- apply: ID lock, freshness check, workspace lock, recovery, freshness check ----
AAcqId == pc["a"] = "start" /\ idLock = NoOne
  /\ idLock' = "a" /\ SetPc("a", "hasId")
  /\ UNCHANGED <<enumLock, wsLock, disk, base, todo, done, rbFailed, jvars>>
ACheck1 == pc["a"] = "hasId"
  /\ (IF disk = base["a"]
        THEN SetPc("a", "fresh1") /\ UNCHANGED <<idLock, enumLock, wsLock>>
        ELSE SetPc("a", "rejected") /\ Release("a"))
  /\ UNCHANGED <<disk, base, todo, done, rbFailed, jvars>>
AAcqWs == pc["a"] = "fresh1" /\ wsLock = NoOne
  /\ wsLock' = "a" /\ SetPc("a", "ws")
  /\ UNCHANGED <<idLock, enumLock, disk, base, todo, done, rbFailed, jvars>>
ACheck2 == pc["a"] = "fresh2"
  /\ (IF disk = base["a"]
        THEN SetPc("a", "prep") /\ UNCHANGED <<idLock, enumLock, wsLock>>
        ELSE SetPc("a", "rejected") /\ Release("a"))
  /\ UNCHANGED <<disk, base, todo, done, rbFailed, jvars>>

\* ---- journal recovery and journal write (shared) ----
\* The new workspace-lock holder first rolls back a leftover journal, then
\* continues (direct: prepare; apply: second freshness check).
Recover(p) == pc[p] = "ws"
  /\ (IF jrnl # NoOne THEN disk' = jbase ELSE disk' = disk)
  /\ jrnl' = NoOne /\ UNCHANGED jbase
  /\ SetPc(p, IF p = "d" THEN "prep" ELSE "fresh2")
  /\ UNCHANGED <<idLock, enumLock, wsLock, base, todo, done, rbFailed>>
WriteJournal(p) == pc[p] = "prep"
  /\ jrnl' = p /\ jbase' = disk                 \* backups are taken from the files as they are now
  /\ todo' = [todo EXCEPT ![p] = Files] /\ done' = [done EXCEPT ![p] = {}]
  /\ SetPc(p, "promote")
  /\ UNCHANGED <<idLock, enumLock, wsLock, disk, base, rbFailed>>

\* ---- promotion, failure, compensation (shared) ----
Promote(p) == pc[p] = "promote" /\ todo[p] # {}
  /\ \E f \in todo[p] :
       /\ disk' = [disk EXCEPT ![f] = base[p][f] + 1]
       /\ todo' = [todo EXCEPT ![p] = @ \ {f}]
       /\ done' = [done EXCEPT ![p] = @ \cup {f}]
  /\ UNCHANGED <<pc, idLock, enumLock, wsLock, base, rbFailed, jvars>>
Commit(p) == pc[p] = "promote" /\ todo[p] = {}
  /\ SetPc(p, "committed") /\ Release(p)
  /\ jrnl' = NoOne                              \* removing the journal is the commit point
  /\ UNCHANGED <<disk, base, todo, done, rbFailed, jbase>>
Fail(p) == pc[p] = "promote" /\ todo[p] # {}      \* a failure_mode raised before the last file
  /\ SetPc(p, "rollback")
  /\ UNCHANGED <<idLock, enumLock, wsLock, disk, base, todo, done, rbFailed, jvars>>
Rollback(p) == pc[p] = "rollback" /\ done[p] # {}
  /\ \E f \in done[p] :
       /\ done' = [done EXCEPT ![p] = @ \ {f}]
       /\ IF RollbackMayFail
            THEN \/ (disk' = [disk EXCEPT ![f] = jbase[f]] /\ UNCHANGED rbFailed)
                 \/ (UNCHANGED disk /\ rbFailed' = TRUE)
            ELSE disk' = [disk EXCEPT ![f] = jbase[f]] /\ UNCHANGED rbFailed
  /\ UNCHANGED <<pc, idLock, enumLock, wsLock, base, todo, jvars>>
RolledBack(p) == pc[p] = "rollback" /\ done[p] = {}
  /\ SetPc(p, "rolledBack") /\ Release(p)
  /\ jrnl' = (IF rbFailed THEN jrnl ELSE NoOne)    \* the journal is kept when compensation failed
  /\ UNCHANGED <<disk, base, todo, done, rbFailed, jbase>>
Crash(p) == CanCrash /\ pc[p] = "promote"
  /\ SetPc(p, "crashed") /\ Release(p)
  /\ UNCHANGED <<disk, base, todo, done, rbFailed, jvars>>

Terminated == /\ \A p \in Procs : pc[p] \in Terminal
  /\ UNCHANGED vars

Next ==
  \/ DAcqId \/ DAcqEnum \/ DRecover \/ DAcqWs \/ AAcqId \/ ACheck1 \/ AAcqWs \/ ACheck2
  \/ \E p \in Procs : Recover(p) \/ WriteJournal(p) \/ Promote(p) \/ Commit(p) \/ Fail(p)
                      \/ Rollback(p) \/ RolledBack(p) \/ Crash(p)
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
\* When no journal is pending, files move together; a pending journal is replayed by the next lock holder.
FilesConsistent == (Quiescent /\ jrnl = NoOne) => disk[1] = disk[2]
\* What a pending journal would restore is itself a consistent state.
Recoverable == jrnl # NoOne => jbase[1] = jbase[2]
\* Without crashes or failed compensation, no committed update is lost.
NoLostUpdate == (Quiescent /\ ~Faulted) => (disk[1] = CommitCount /\ disk[2] = CommitCount)
==================================================================================
