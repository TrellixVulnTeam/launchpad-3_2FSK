SET client_min_messages=ERROR;

ALTER TABLE BranchMergeProposal
  ADD COLUMN superceded_proposal INT REFERENCES BranchMergeProposal;

-- This constraint is no longer correct and a database level
-- constraint isn't going to help now due to model changes.
ALTER TABLE BranchMergeProposal
  DROP CONSTRAINT branchmergeproposal_source_branch_key;

CREATE INDEX branchmergeproposal_superceded_proposal
  ON BranchMergeProposal(superceded_proposal);

INSERT INTO LaunchpadDatabaseRevision VALUES (88, 95, 0);
