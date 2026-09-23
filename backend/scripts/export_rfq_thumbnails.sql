-- Export bom_items thumbnails for one RFQ2 RFQ, as JSON lines of
-- {"part_number": "<raw bom_items.part_number>", "thumbnail": "<data URI>"}
-- for scripts/import_1994_thumbnails.py to read.
--
-- PLM and RFQ2 are separate databases, so this runs against the RFQ2
-- database and its output is copied into a place the PLM container can
-- read. Usage (replace :rfq_id, or set it with psql -v rfq_id=26):
--
--   docker exec -i rfq2-postgres-1 psql -U rfq_user -d rfq_db \
--       -v rfq_id=26 -f scripts/export_rfq_thumbnails.sql -t -A \
--       > /tmp/rfqNN_thumbs.jsonl
--
-- part_number looks like "S00G77-000\n206_887_233" (Brose number, newline,
-- VW number with underscores) - import_1994_thumbnails.py parses the
-- second line and turns underscores into dots to match customer_part_number.
select json_build_object('part_number', bi.part_number, 'thumbnail', bi.thumbnail)::text
from bom_items bi
join bom_groups bg on bi.bom_group_id = bg.id
where bg.rfq_id = :rfq_id
  and bi.thumbnail is not null;
