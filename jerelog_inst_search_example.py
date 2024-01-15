import jerelog_parser as jlog
from jerelog_parser import VerilogModule
import time
import argparse
import os

class CustomHelpFormatter(
    argparse.RawDescriptionHelpFormatter,
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.MetavarTypeHelpFormatter):
    pass

help_text = """
This is an example script of how to use the different hierarchy path search methods within the jerelog_parser library
"""

if __name__ == "__main__":

    start_time = time.time()

    default_module = "" # optional: change the default to a module you'll report on often

    parser = argparse.ArgumentParser(
        formatter_class = CustomHelpFormatter,
        description = help_text
    )
    parser.add_argument("-m", "--module",       dest = "module",        type = str,  nargs = "?", default = default_module, help = "module to analyze and generate reports on")
    parser.add_argument("-r", "--report_hier",  dest = "report_hier",   type = str,  nargs = "?", default = default_module, help = "module to search for \'-m\' defined module under")
    parser.add_argument("-M", "--max_depth",    dest = "max_depth",     type = int,  nargs = "?", default = 0,              help = "number of levels of hierarchy you want to analyze (0 means no limit)")
    parser.add_argument("-s", "--search_method",dest = "search_method", type = int,  nargs = "?", default = 1,              help = "select a search method: 1 = exact module type, 2 = module type contains string, 3 = instance name contains string")
    parser.add_argument("-u", "--print_unused", dest = "print_unused",  action='store_true',                                help = "generate list of unused modules that were read in")
    parser.add_argument("-d", "--debug_mode",   dest = "debug_mode",    action='store_true',                                help = "enable printing of non-essential debug messages, recommend running only on single file")

    args            = parser.parse_args()
    analyze_module  = str(args.module)
    top_module      = str(args.report_hier)
    max_depth       = int(args.max_depth)
    search_method   = int(args.search_method)
    print_unused    = args.print_unused
    jlog.debug_mode = args.debug_mode # debug mode enables some prints within jerelog_parser, needs to be set to either True or False

    # read in a verilog_modules.db file
    if os.path.exists("verilog_modules.db"):
        jlog.retrieve_verilog_modules()
    else:
        print(f"{jlog.color.RED}ERROR{jlog.color.RESET} : verilog_modules.db does not exist, this file is required to run this script")

    if analyze_module != "" and top_module != "":
        out_file = open(f"{analyze_module}_under_{top_module}.txt", 'w')

        if search_method == 1:
            jlog.find_all_instances(analyze_module, top_module, out_file)
        elif search_method == 2:
            jlog.find_all_instances_re(analyze_module, top_module, out_file)
        elif search_method == 3:
            jlog.find_all_instances_iname_re(analyze_module, top_module, out_file)
        else:
            print(f"{jlog.color.RED}ERROR{jlog.color.RESET} : invalid search method selected")

    end_time = time.time()

    print(f"INFO : Execution time = {end_time - start_time} seconds")