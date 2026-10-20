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
def bootstrap: (type == "object")
  and exact_keys(["active_initiatives","attention","attention_owner","executive_summary","is_demo","period_label","published_at","pulse","reviewed_issues","sprint_id","team"])
  and (.sprint_id | (type == "string") and test("^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$"))
  and (.period_label | type == "string")
  and (.published_at | type == "string")
  and (.team | type == "string")
  and (.executive_summary | type == "string")
  and (.pulse | type == "string")
  and (.attention | type == "string")
  and (.attention_owner | type == "string")
  and (.is_demo | type == "boolean")
  and (.reviewed_issues | (type == "number") and . >= 0 and . == floor)
  and (.active_initiatives | (type == "number") and . >= 0 and . == floor);
(type == "object")
and .format == "sprint-intelligence-parquet"
and (.history | entry and .path == "history.parquet")
and (.sprints | (type == "array") and length > 0 and all(.[]; sprint_entry))
and ([.sprints[].id] | unique | length) == (.sprints | length)
and (
  (.manifest_version == 1 and exact_keys(["format","history","manifest_version","sprints"]))
  or
  (.manifest_version == 2 and exact_keys(["bootstrap","format","history","manifest_version","sprints"])
    and (.bootstrap | bootstrap)
    and ([.sprints[].id] | index(.bootstrap.sprint_id)) != null)
)
