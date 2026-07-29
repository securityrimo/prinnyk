from core.nsf_string import NSFStringExtractor


nsf = NSFStringExtractor(
    "workspace/unpack/SCRIPT/G9system.nsf"
)


nsf.parse_header()


nsf.save_json(
    "workspace/nsf/G9system_strings.json"
)
