# Shape validation only. CI then checks file set, byte length, SHA-256 and magic.
def exact_keys($names): (keys | sort) == ($names | sort);
def checksum: (type == "string") and test("^[0-9a-f]{64}$");
def entry: (type == "object") and exact_keys(["path","size","sha256"])
  and (.size | (type == "number") and . > 100 and . <= 2000000 and . == floor)
  and (.sha256 | checksum);
def sprint_entry: (type == "object")
  and exact_keys(["id","path","schema_version","size","sha256"])
  and (.id | (type == "string") and test("^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$"))
  and (.path == ("sprints/" + .id + ".parquet"))
  and (.schema_version == 1 or .schema_version == 2)
  and (.size | (type == "number") and . > 100 and . <= 2000000 and . == floor)
  and (.sha256 | checksum);
(type == "object") and exact_keys(["format","history","manifest_version","sprints"])
and .manifest_version == 1
and .format == "sprint-intelligence-parquet"
and (.history | entry and .path == "history.parquet")
and (.sprints | (type == "array") and length > 0 and all(.[]; sprint_entry))
and ([.sprints[].id] | unique | length) == (.sprints | length)
