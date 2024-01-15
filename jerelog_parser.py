#!/usr/sepp/bin/python3.7

r"""
Copyright (C) 2024 Analog Devices, Inc., All Rights Reserved.

This module contains a library of functions designed to aide in writing Python scripts around Verilog files
where Hierarchy knowledge is required.

To use this library, it is recommended that the jerelog_parser be imported as well as the class 'VerilogModule'.
    -This class is used as the standard format to transfer module information between functions contained in this library.

This library does not require the use of a Verilog interpreter such as Icarus or Xcelium.

This library contains an example script showing some basic applications of the functions contained within this library.
"""

import argparse
import os
import time
import re
import sqlite3
import pickle
import signal
import math

class CustomHelpFormatter(
    argparse.RawDescriptionHelpFormatter,
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.MetavarTypeHelpFormatter):
    pass

# help prompt, look how nice it is in Python!
example_script_help_text = """
INFO:
    This script contains only a basic example of how to use functions defined
    in this library. It is recommended that this library be imported and integrated
    to your own scripting.
"""

class color:
    GREY        = "\033[38;5;246m"
    GREEN       = "\033[38;5;10m"
    YELLOW      = "\033[38;5;220m"
    WHITE       = "\033[38;5;255m"
    RED         = "\033[38;5;196m"
    RESET       = "\033[0;0m"
    GREEN_BG    = "\033[48;5;10m\033[38;5;232m"  # bold black text on green background
    YELLOW_BG   = "\033[48;5;220m\033[38;5;232m" # bold black text on yellow background
    GREY_BG     = "\033[48;5;246m\033[38;5;232m" # bold black text on grey background
    RED_BG      = "\033[48;5;196m\033[38;5;232m" # bold white text on red background

class VerilogModule:
    """
    Custom class to hold saved attributes about a Verilog Module in
    a format which can aide parsing throughout functions in jerelog_parser.

    ATTRIBUTES:
        name: module name
        inputs: list of module inputs
        outputs: list of module outputs
        submodules: list of instances as well as their type

        (useful for VS Code CTRL + Click navigation):
        filepath: path to the file where this module is defined
        linenum: line number on filepath where module is defined
        startcol: column number on filepath where module is defined <points to the end of the module name>
    """
    def __init__(self, name, inputs, outputs, submodules, filepath, linenum, startcol):
        self.name       = name
        self.inputs     = inputs
        self.outputs    = outputs
        self.submodules = submodules
        self.filepath   = filepath
        self.linenum    = linenum
        self.startcol   = startcol

seperating_char = "." # use this to define what character separates the hierarchies when reporting paths.

verilog_modules = []
module_list = []
multi_defined_list = []
used_module_list = []
used_file_list = []
unused_file_list = []
verilog_define_variables = []

def read_module_info(module_name):
    """return information about a module if it is defined

    Args:
        module_name (string): the name of the module you want to get information about

    Returns:
        name: module name
        inputs: list of module inputs
        outputs: list of module outputs
        submodules: list of instances as well as their type

        (useful for VS Code CTRL + Click navigation):
        filepath: path to the file where this module is defined
        linenum: line number on filepath where module is defined
        startcol: column number on filepath where module is defined
    """
    for module in verilog_modules:
        if module.name == module_name:
            return {
                "name": module.name,
                "inputs": module.inputs,
                "outputs": module.outputs,
                "submodules": module.submodules,
                "filepath": module.filepath,
                "linenum": module.linenum,
                "startcol": module.startcol
            }

def get_uncommented(line, block_comment):
    """pass in a line and return the section that isn't blocked by a comment

    Args:
        line (string): raw line
        block_commment (bool): true if line starts in an active block comment

    Returns:
        out_line (string): line without the comments
        block_comment (bool): true if line ends in an active block comment
    """
    i = 0
    out_line = ""

    if not block_comment:
        while(line.find("//*") != -1):
            line = line.replace("//*", "//")

    while i < len(line):
        if block_comment:
            if line[i:].find("*/") != -1:
                # add nothing to the running string, but move the index to the end of block comment and clear the flag
                out_line_temp = ""
                block_comment = False
                i = i + line[i:].find("*/") + len("*/")
            else:
                # add nothing more since the rest of the line is commented out
                out_line_temp = ""
                i = len(line)
        else:
            if line[i:].find("/*") != -1:
                # add anything before the block comment and set the block_comment flag
                out_line_temp = line[i: i + line[i:].find("/*")]
                block_comment = True
                i = i + line[i:].find("/*")
            else:
                if line[i:].find("//") != -1:
                    # add nothing past the comment since the rest of the line is commented out
                    out_line_temp = line[i:line[i:].find("//")]
                    i = len(line)
                else:
                    # no more comments, return the rest of the line
                    out_line_temp = line[i:]
                    i = len(line)

        out_line = out_line + out_line_temp

    return out_line, block_comment

def check_ifdefs(line, inside_ifdef, ifdef_stack):
    """check for valid \`ifdefs and \`defines

    Args:
        line (string): a line with no comments.
        inside_ifdef (bool): store if the current line exists within an \`ifdef already.
        ifdef_stack (array of strings): stack of variables being used for \`ifdefs (pop as the \`endif is detected).

    Returns:
        filtered_line: filters out the existing line if it is blocked by ifdefs.
        inside_ifdef (bool): PASSTHROUGH store if the current line exists within an \`ifdef already.
        ifdef_stack (array of strings): PASSTHROUGH stack of variables being used for \`ifdefs (pop as the \`endif is detected).
    """

    global verilog_define_variables
    temp_line = line.strip()
    temp_line = temp_line.replace("\t", " ")
    filtered_line = ""

    # Check for `ifdef, `else, `define and `endif
    if temp_line.startswith('`ifdef'):
        ifdef_stack.append(temp_line.split(' ')[-1])
        inside_ifdef = ifdef_stack[-1] in verilog_define_variables
    elif temp_line.startswith('`protected'):
        ifdef_stack.append('protected')
        inside_ifdef = ifdef_stack[-1] in verilog_define_variables
    elif temp_line.startswith('`ifndef'):
        ifdef_stack.append(temp_line.split(' ')[-1])
        inside_ifdef = len(ifdef_stack) == 0 and ifdef_stack[-1] not in verilog_define_variables
    elif temp_line.startswith('`endif'):
        ifdef_stack.pop()
        inside_ifdef = len(ifdef_stack) > 0 and ifdef_stack[-1] in verilog_define_variables
    elif temp_line.startswith('`endprotected'):
        ifdef_stack.pop()
        inside_ifdef = len(ifdef_stack) > 0 and ifdef_stack in verilog_define_variables
    elif temp_line.startswith('`else'):
        inside_ifdef = len(ifdef_stack) > 0 and ifdef_stack[-1] not in verilog_define_variables
    elif temp_line.startswith('`define'):
        if (inside_ifdef) or (len(ifdef_stack) == 0):
            # Parse `define variables and append them to verilog_define_variables
            tokens = temp_line.split(' ')
            if len(tokens) >= 2:
                verilog_define_variables.append(tokens[1])
    else:
        # Include the line if inside a valid `ifdef block or not inside any `ifdef
        if inside_ifdef or len(ifdef_stack) == 0:
            filtered_line = line

    return filtered_line, inside_ifdef, ifdef_stack

def get_module_name(line):
    """Reads in a line where a module is initially defined and returns the module name

    Args:
        line (string): starts with "module " and has a module name on it

    Returns:
        string: just the module name, does not return the module IO
    """
    module_name = ""

    start_idx = line.find("module ") + len("module ")

    line = line[start_idx:].strip()

    end_idx = 0
    while(1):
        if line[:end_idx].find(" ") != -1: break
        elif line[:end_idx].find("\t") != -1: break
        elif line[:end_idx].find("(") != -1: break
        elif line[:end_idx].find(";") != -1: break
        elif line[:end_idx].find("\n") != -1: break
        elif end_idx == len(line):
            end_idx = len(line) + 1
            break
        else: end_idx = end_idx + 1

    if end_idx != -1:
        module_name = line[:end_idx - 1]

    return module_name

def get_one_line_code(module_code):
    """
    Replace all newlines, tabs, double spaces with single space to simplify reading

    Args:
        module_code (array of strings): pass in the module
    """
    one_line_code = ""

    for line in module_code:
        one_line_code = one_line_code + line

    one_line_code = one_line_code.replace("\n", " ")
    one_line_code = one_line_code.replace("\t", " ")
    one_line_code = one_line_code.replace(", ", ",")
    one_line_code = one_line_code.replace("# (", "#(")

    # skip over parameters if any
    while 1:
        if one_line_code.find("#(") != -1:
            i = one_line_code.find("#(") + len("#(")
            parenth_lvl = 1
            while 1:
                if one_line_code[i] == ")":
                    parenth_lvl = parenth_lvl - 1
                if one_line_code[i] == "(":
                    parenth_lvl = parenth_lvl + 1
                i = i + 1
                if parenth_lvl == 0:
                    # print(one_line_code[one_line_code.find("#("):i])
                    break
            one_line_code = one_line_code.replace(one_line_code[one_line_code.find("#("):i], "")
        else:
            break

    # skip over event-triggered if any
    while 1:
        if one_line_code.find("@(") != -1:
            i = one_line_code.find("@(") + len("@(")
            parenth_lvl = 1
            while 1:
                if one_line_code[i] == ")":
                    parenth_lvl = parenth_lvl - 1
                if one_line_code[i] == "(":
                    parenth_lvl = parenth_lvl + 1
                i = i + 1
                if parenth_lvl == 0:
                    # print(one_line_code[one_line_code.find("@("):i])
                    break
            one_line_code = one_line_code.replace(one_line_code[one_line_code.find("@("):i], "")
        else:
            break

    while(one_line_code.find("  ") != -1):
        one_line_code = one_line_code.replace("  ", " ")

    # debug that all whitespace other than a single space is removed
    # print(one_line_code)
    return one_line_code

def get_module_type_name(type_name_string):
    """parse an instance's instantiation for that instance's type and instance name

    Args:
        type_name_string (string): contains two words seperated by whitespace only

    Returns:
        type_string: instance's type
        name_string: instance's name
    """

    type_string = ""
    name_string = ""

    # get rid of leading whitespace
    type_name_string = type_name_string.strip()

    type_string = type_name_string[:type_name_string.find(" ") + len(" ")]
    name_string = type_name_string[type_name_string.find(" ") + len(" "):]

    type_string = type_string.strip()
    name_string = name_string.strip()

    # if debug_mode:
    #     print(f"sub-instance type = {type_string}, sub-instance name = {name_string}")

    return type_string, name_string

def parse_ports(verilog_text):
    """get the ports of a module using regular expressions

    Args:
        verilog_text (string): pass in the single-line version of the module's code

    Returns:
        ports: a list of all ports with (in order) port direction, name, and width
    """
    ports = []
    port_pattern = re.compile(r'\b(input|output|inout)\s+(?:reg|logic|bit)?\s*(?:(\[[^\]]*\])\s*)?(\w+(?:\s*,\s*\w+)*)\s*[;,)]', re.MULTILINE)

    for match in port_pattern.finditer(verilog_text):
        port_type, bit_width, port_group = match.groups()
        port_names = [port.strip() for port in port_group.split(',')]

        for port_name in port_names:
            bit_width_formatted = bit_width.strip() if bit_width else ''
            ports.append((port_type, port_name, bit_width_formatted))

    return ports

# reserved words/characters that should not be the names of instances or modules
invalid_module_names = [
    'if', 'else',
    'begin', 'end',
    'case', 'endcase',
    'generate', 'endgenerate',
    'initial',
    'wire',
    'logic',
    'parameter',
    'localparam',
    'assign',
    'always',
    'always_ff',
    'for',
    '$display',
    '$finish',
    '@',
]

def save_module_attributes(module, one_line_module_code):
    """retreive all information about a verilog module

    Args:
        module (string): name of the module
        one_line_module_code (string): uncommented, single-line version of the verilog code

    Returns:
        input_list: list of all inputs to this module
        output_list: list of all outputs to this module
        submod_list: list of all submodules called by this module
    """

    def handle_ctrl_c(signal, frame):
        # print("\nCtrl+C detected. Exiting gracefully...")
        print(f"\nremaining line at exit: {one_line_module_code[i:]}")
        exit()
    if debug_mode:
        print(f"{color.GREEN}INFO{color.RESET} : getting attributes for module {module} ...")
        signal.signal(signal.SIGINT, handle_ctrl_c)

    i = 0
    input_list = []
    output_list = []
    submod_list = []

    ports = parse_ports(one_line_module_code)

    if debug_mode:
        print(ports)

    for port_type, port_name, port_width in ports:
        if port_type == "input":
            input_list.append([port_type, port_name, port_width])
        if port_type == "output":
            output_list.append([port_type, port_name, port_width])
        if port_type == "inout":
            input_list.append([port_type, port_name, port_width])
            output_list.append([port_type, port_name, port_width])

    while i < len(one_line_module_code):

        # module definition handling
        if one_line_module_code[i:].find("module " + module) != -1:
            # avoid an infinite loop if the module name passed in is blank
            # that's still an error but this avoids chasing a red-herring
            if one_line_module_code[i:].find(";") != -1:
                i = i + one_line_module_code[i:].find(";") + len(";")
            else:
                i = len(one_line_module_code)

        # wire definition handling
        elif one_line_module_code[i:].find("wire ") == 0:
            # not keeping track of wires for now...
            i = i + one_line_module_code[i:].find(";") + len(";")

        # assignment definition handling
        elif one_line_module_code[i:].find("assign ") == 0:
            # not keeping track of assigns for now...
            i = i + one_line_module_code[i:].find(";") + len(";")

        elif one_line_module_code[i:].find("(") != -1:
            submod_start = i
            submod_end = i + one_line_module_code[i:].find("(")

            # mainly to filter things like "end" or "endcase" out
            while(1):
                found_one = False
                for inval_mod_name in invalid_module_names:
                    if one_line_module_code[submod_start:submod_end].strip().startswith(inval_mod_name + " "):
                        submod_start = submod_start + one_line_module_code[submod_start:submod_end].find(inval_mod_name + " ") + len(inval_mod_name + " ")
                        found_one = True
                if not found_one:
                    break

            if one_line_module_code[submod_start:submod_end].find(";") == -1:
                inst_type, inst_name = get_module_type_name(one_line_module_code[submod_start:submod_end])
                inst_type_name_cat = inst_type + inst_name # to simplify filtering code, save type and name into a single string to check for any special characters
                if (
                    # make sure the type and name aren't blank
                    (inst_type != '') and
                    (inst_name != '') and

                    # make sure the type or name isn't a reserved word
                    (inst_type not in invalid_module_names) and
                    (inst_name not in invalid_module_names) and

                    # neither instance name or type should have these special characters...
                    (inst_type_name_cat.find("=") == -1) and
                    (inst_type_name_cat.find(":") == -1) and
                    (inst_type_name_cat.find(".") == -1) and
                    (inst_type_name_cat.find("[") == -1) and
                    (inst_type_name_cat.find("]") == -1) and
                    (inst_type_name_cat.find("$") == -1) and
                    (inst_type_name_cat.find("<") == -1) and
                    (inst_type_name_cat.find(">") == -1) and
                    (inst_type_name_cat.find(" ") == -1)
                    ):
                    submod_list.append([inst_type, inst_name])

            i = i + one_line_module_code[i:].find(";") + len(";")

        # avoid getting stuck in a loop if none of the above are met
        else:
            if one_line_module_code[i:].find(";") != -1:
                i = i + one_line_module_code[i:].find(";") + len(";")
            else:
                i = len(one_line_module_code)

    if debug_mode:
        print(f"\t{color.YELLOW}INPUTS{color.RESET}        : {input_list[:len(input_list)]}")
        print(f"\t{color.YELLOW}OUTPUTS{color.RESET}       : {output_list[:len(output_list)]}")
        for inst_t, inst in submod_list:
            print(f"\t{color.GREY}CALLED MODULE{color.RESET} : instance = {inst},\ttype = {inst_t}")

    return input_list, output_list, submod_list

def replace_env_variable(filepath):
    """
    Pass in a filepath with environment variables and returns the
    same filepath with the environment varialbe replaced by that variable's value.

    Args:
        filepath (string): filepath with environment variables

    Returns:
        string: filepath where the environment variables are replaced by the value
    """
    # Find environment variable placeholders in the file path
    env_var_start = filepath.find('$')
    env_var_end = filepath.find(os.path.sep, env_var_start)

    # If an environment variable placeholder is found
    while env_var_start != -1 and env_var_end != -1:
        # Extract the environment variable name
        env_var_name = filepath[env_var_start + 1:env_var_end]

        # Get the value of the environment variable
        env_var_value = os.environ.get(env_var_name, '')

        if debug_mode:
            print(f"INFO : replacing ${env_var_name} with {env_var_value}")

        # Replace the environment variable placeholder with its value
        filepath = filepath[:env_var_start] + env_var_value + filepath[env_var_end:]

        # Find the next environment variable placeholder
        env_var_start = filepath.find('$')
        env_var_end = filepath.find(os.path.sep, env_var_start)

    return filepath

def parse_verilog(filename):
    """Reads in a verilog file and saves information about the modules contained within to verilog_modules

    Args:
        filename (string): path to Verilog file intended to be parsed
    """

    if filename.find("$") != -1:
        filename = replace_env_variable(filename)

    if os.path.isfile(filename):
        print(f"{color.GREEN}INFO{color.RESET} : reading in {filename} ...")
        file = open(filename, 'r')

        active_module = False
        block_comment = False
        inside_ifdef = False
        ifdef_stack = []
        line_number = 0

        module_code = []
        ifdef_stack = []
        global verilog_modules
        global module_list
        global multi_defined_list

        for line in file:
            line_number = line_number + 1

            uncommented_line, block_comment = get_uncommented(line, block_comment)
            uncommented_line, inside_ifdef, ifdef_stack = check_ifdefs(uncommented_line, inside_ifdef, ifdef_stack)

            if (uncommented_line != "") or (uncommented_line != "\n"):

                # debug exactly what pass through the above filters (commenting and `ifdef filters)
                # if debug_mode:
                #     print(uncommented_line[:len(uncommented_line) - 1])

                # endmodule case
                if uncommented_line.find("endmodule") != -1:
                    if active_module == False:
                        print("ERROR : endmodule detected before a 'module' definition was established")
                        exit()
                    if debug_mode:
                        print(f"INFO : End of module \'{module}\' on line {str(line_number)}")
                    active_module = False

                    # module is finished here, save off the attributes and reset the module_code variable for the next module (if any)
                    module_code.append(uncommented_line)
                    one_line_module_code = get_one_line_code(module_code)
                    if module not in module_list:
                        module_list.append(module)
                        input_list, output_list, submod_list = save_module_attributes(module, one_line_module_code)
                        verilog_modules.append(VerilogModule(module, input_list, output_list, submod_list, filename, start_line, start_column))
                    else:
                        print(f"{color.YELLOW}WARNING{color.RESET} : module named {module} already defined")
                        multi_defined_list.append([module, filename, start_line, start_column])
                    module_code = []

                # module definition case
                elif (uncommented_line.strip().startswith("module ")) or (uncommented_line.strip().startswith("module\t")) or (uncommented_line.find(" module ") != -1):
                    module = get_module_name(uncommented_line)
                    start_line = line_number
                    start_column = uncommented_line.find(module) + len(module) + 1
                    if debug_mode:
                        print(f"INFO : Reading in module \'{module}\' on line {str(line_number)}")
                    active_module = True
                    module_code.append(uncommented_line)

                # between a 'module' and an 'endmodule'
                elif active_module:
                    module_code.append(uncommented_line)

        if active_module:
            print(f"{color.RED}ERROR{color.RESET} : module \'{module}\' did not have a corresponding endmodule")
            exit()

        file.close()
    else:
        print(f"ERROR : {filename} was not found")

def report_on_module(module):
    """print all saved information for a given module

    Args:
        module (string): this should be the module name (note, NOT the instance name)
    """

    top_module_info = read_module_info(module)

    print("\n-------------------------------------")
    print(f"INFO : report on module {module}...")
    if top_module_info:
        print(f"NAME:       {top_module_info['name']}")
        print(f"FILEPATH:   {top_module_info['filepath']}:{top_module_info['linenum']}:{top_module_info['startcol']}")
        print(f"INPUTS:     {top_module_info['inputs']}")
        print(f"OUTPUTS:    {top_module_info['outputs']}")
        print(f"INSTANCE:   {top_module_info['submodules']}")
    else:
        print(f"{color.RED}ERROR{color.RESET} : module {module} was not found.")
    print("-------------------------------------\n")

def report_hierarchy(top_module, hier_num=0, report_unused=False, max_depth=0):
    """This function recursively reads in the module information and prints out a hierarchical tree.

    Args:
        top_module (string): pass in module to report hierarchy on
        hier_num (int, optional): keeps track of how many times to indent and the current level of recursion. Default to 0.
        report_unused (bool, optional): reports if any modules are read in but unused. Defaults to False.
        max_depth (int, optional): if NOT set to 0, sets the number of levels below top_module you want to report.
    """
    top_module_info = read_module_info(top_module)

    global used_module_list # keep a running list of all modules used
    global used_file_list   # keep a running list of all files used
    global unused_file_list # keep a running list of all files used
    global out_file         # due to recursion, the output file must be stored as a global variable

    if hier_num == 0:
        out_file = open("hierarchy_" + top_module + ".txt", 'w')
        if report_unused:
            used_module_list = [top_module]
        if max_depth != 0:
            out_file.write(f"INFO : max_depth set to {max_depth}\n\n")
        print(f"\nINFO : reporting hierarchy below module {top_module}...\n")
        print(top_module)
        out_file.write(top_module + "\n")

    indent      = '| ' * (hier_num + 1)
    file_indent = '\t' * (hier_num + 1)
    if top_module_info:
        if top_module_info['filepath'] not in used_file_list:
            used_file_list.append(top_module_info['filepath'])
        for i_type, i_name in top_module_info['submodules']:
            print(f"{indent}{i_name} ({i_type})")
            out_file.write(f"{file_indent}{i_name} ({i_type})\n")
            used_module_list.append(i_type)
            if max_depth == 0 or hier_num < max_depth - 1:
                report_hierarchy(i_type, hier_num + 1, max_depth=max_depth)

    # to avoid printing on all levels of this function which gets called recursively, only run
    # the following code when on the highest level of hierarchy
    # (every recursive call of this function increases the hierarchy number by one)
    if hier_num == 0:
        out_file.close()
        unique_used_module_list = list(set(used_module_list))
        if report_unused:
            print(f"\nINFO : generating report of unused modules under {top_module}...")
            unique_unused_module_list = []

            # report all unused modules over STDOUT
            for module in verilog_modules:
                if module.name not in unique_used_module_list:
                    unique_unused_module_list.append(module)
                    print(f"\tmodule type {module.name} was unused ({module.filepath}:{module.linenum}:{module.startcol})")

            # report all unused files in unused_files.txt
            unused_log_file = open("unused_files.txt", 'w')
            for module in unique_unused_module_list:
                if (module.filepath not in unused_file_list) and (module.filepath not in used_file_list):
                    unused_file_list.append(module.filepath)
                    unused_log_file.write(f"No modules from this file were used : {module.filepath}\n")
            unused_log_file.close()

        print(f"\nINFO : end of hierarchy report")

def find_all_instances(module_type, search_module, outfile, current_path=""):
    """recursively works backwards to find all paths to a certain type of module

    Args:
        module_type (string): the module you're looking for
        search_module (string): the module you're looking under
        outfile (file): file where the report will be written
        current_path (string, optional): the current path being traced backwards
    """
    if current_path == "":
        print(f"{color.GREEN}INFO{color.RESET} : searching for all instances under {search_module} where the module type is '{module_type}'\n")
    start_of_search_path = current_path # save what hierarchy you're currently on here
    for module in verilog_modules:
        # cycle through all sub-modules to find if a given module is found
        for i_type, i_name in module.submodules:
            append_path = start_of_search_path # re-initialize for each sub-module
            if i_type == module_type:
                if current_path == "":
                    append_path = f"{i_name}"
                else:
                    append_path = f"{i_name}{seperating_char}{start_of_search_path}"

                if module.name == search_module:
                    print(f"INFO : Found path:  = {module.name}{seperating_char}{append_path}")
                    outfile.write(f"{module.name}{seperating_char}{append_path}\n")
                find_all_instances(module.name, search_module, outfile, current_path=append_path)

def find_all_instances_re(module_type, search_module, outfile, current_path=""):
    """recursively works backwards to find all paths to a certain type of module.
    module_type will contain the string you're looking for in a module
    Follows the regular find_all_instances() function after this first call.

    Args:
        module_type (string): the module you're looking for MUST contain this string
        search_module (string): the module you're looking under
        outfile (file): file where the report will be written
        current_path (string, optional): the current path being traced backwards
    """
    print(f"{color.GREEN}INFO{color.RESET} : searching for all instances under {search_module} where the module type contains the string '{module_type}'\n")
    start_of_search_path = current_path # save what hierarchy you're currently on here
    for module in verilog_modules:
        # cycle through all sub-modules to find if a given module is found
        for i_type, i_name in module.submodules:
            append_path = start_of_search_path # re-initialize for each sub-module
            if i_type.find(module_type) != -1:
                if current_path == "":
                    append_path = f"{i_name}"
                else:
                    append_path = f"{i_name}{seperating_char}{start_of_search_path}"

                if module.name == search_module:
                    print(f"INFO : Found path  = {module.name}{seperating_char}{append_path}")
                    outfile.write(f"{module.name}{seperating_char}{append_path}\n")
                find_all_instances(module.name, search_module, outfile, current_path=append_path)

def find_all_instances_iname_re(module_name, search_module, outfile, current_path=""):
    """recursively works backwards to find all paths to module with a certain name.
    module_name will contain the string you're looking for in a module
    Follows the regular find_all_instances() function after this first call.

    Args:
        module_name (string): the instance name you're looking for MUST contain this string
        search_module (string): the module you're looking under
        outfile (file): file where the report will be written
        current_path (string, optional): the current path being traced backwards
    """
    print(f"{color.GREEN}INFO{color.RESET} : searching for all instances under {search_module} which contain the string '{module_name}'\n")
    start_of_search_path = current_path # save what hierarchy you're currently on here
    for module in verilog_modules:
        # cycle through all sub-modules to find if a given module is found
        for i_type, i_name in module.submodules:
            append_path = start_of_search_path # re-initialize for each sub-module
            if i_name.find(module_name) != -1:
                if current_path == "":
                    append_path = f"{i_name}"
                else:
                    append_path = f"{i_name}{seperating_char}{start_of_search_path}"

                if module.name == search_module:
                    print(f"INFO : Found path  = {module.name}{seperating_char}{append_path}")
                    outfile.write(f"{module.name}{seperating_char}{append_path}\n")
                find_all_instances(module.name, search_module, outfile, current_path=append_path)

def readback_instance_paths(filename):
    """see if any modules were found in the instance search by reading back the generated file to see if it's blank

    Args:
        filename (string): path to the file you want to check
    """
    paths_found = False
    lines = []
    infile = open(filename, 'r')

    for line in infile:
        lines.append(line)

    infile.close()

    if len(lines) >= 1:
        if len(lines[0]) != 0:
            paths_found = True

    return paths_found

def parse_file_list(filelist):
    """read in a list of verilog files, then run parse_verilog() on those files

    Args:
        filelist (string): path to a list of verilog files (ie DUTLIB.f)
    """
    if os.path.isfile(filelist):
        verilog_list_file = open(filelist, 'r')

        for line in verilog_list_file:
            verilog_file = line.strip()
            if not verilog_file.startswith("#"):
                if verilog_file.find("$") != -1:
                    verilog_file = replace_env_variable(verilog_file)
                if os.path.isfile(verilog_file):
                    parse_verilog(verilog_file)
                else:
                    if debug_mode:
                        print(f"INFO : {verilog_file} is not a file")
    else:
        print(f"ERROR : {filelist} is not a file")

def generate_minimized_filelist(filelist):
    """
    read in a filelist and generate a minimized filelist using only
    modules that are in the used_file_list, generated during in report_hierarchy()

    Args:
        filelist (string): path to a filelist
    """
    global unused_file_list

    if os.path.isfile(filelist):
        og_verilog_list = open(filelist, 'r')
        minimized_verilog_list = open(f"minimized_filelist.f", 'w')

        for line in og_verilog_list:
            verilog_file = line.strip()
            if not verilog_file.startswith("#"):
                if verilog_file.find("$") != -1:
                    verilog_file = replace_env_variable(verilog_file)
                if os.path.isfile(verilog_file):
                    if verilog_file not in unused_file_list:
                        minimized_verilog_list.write(f"{line}")
                elif verilog_file.startswith("+incdir+"):
                    # write out all include-directory lines
                    minimized_verilog_list.write(f"{line}")
                else:
                    if debug_mode:
                        print(f"INFO : {verilog_file} is not a file")
    else:
        print(f"ERROR : {filelist} is not a file")


def save_verilog_modules():
    """
    Saves the existing verilog_modules list to a verilog_modules.db file to be quickly accessed in the future
    """
    print(f"INFO : saving modules to verilog_modules.db ...")

    # Serialize the list using pickle to store in the database
    serialized_modules = pickle.dumps(verilog_modules)

    # Connect to SQLite3 database
    conn = sqlite3.connect('verilog_modules.db')

    # Create a table to store serialized data
    conn.execute('''CREATE TABLE IF NOT EXISTS modules
                    (id INTEGER PRIMARY KEY,
                    data BLOB)''')

    # Insert serialized data into the database
    conn.execute('INSERT INTO modules (data) VALUES (?)', (sqlite3.Binary(serialized_modules),))

    # Commit changes and close connection
    conn.commit()
    conn.close()

def report_multi_defined():
    """
    Generates STDOUT and writes out file to report all modules that are defined in multiple locations.

    This is typically either two independant definitions, or reading in the same file more than once by accident.

    The report will be written out to multi_defined_module_list.txt if any exist.

    Returns True if no duplicates found
    """
    global multi_defined_list
    global verilog_modules

    if os.path.exists("multi_defined_module_list.txt"):
        os.remove("multi_defined_module_list.txt")

    if len(multi_defined_list) != 0:

        multi_define_report = open("multi_defined_module_list.txt", 'w')

        for module, filepath, start_line, start_col in multi_defined_list:
            print(f"{color.YELLOW}WARNING{color.RESET} : module {module} defined at {filepath}:{start_line}:{start_col} was previously defined")
            multi_define_report.write(f"module {module} defined in {filepath} was previously defined\n")
            if debug_mode:
                report_on_module(module)
        multi_define_report.close()
        return False
    else:
        print(f"{color.GREEN}INFO{color.RESET} : No modules defined more than once! :)")
        return True

def retrieve_verilog_modules():
    """
    Find the verilog_modules.db file and use it to overwrite the existing verilog_modules.
    This will be faster than reading in the modules again.
    """
    global verilog_modules

    if os.path.isfile('verilog_modules.db'):
        if debug_mode:
            print(f"INFO : reading in verilog_modules.db ...")

        # Connect to the database
        conn = sqlite3.connect('verilog_modules.db')

        # Retrieve the serialized data from the database
        cursor = conn.execute('SELECT data FROM modules LIMIT 1')  # Assuming only one record exists
        serialized_data = cursor.fetchone()[0]

        # Deserialize the data back into verilog_modules list
        verilog_modules = pickle.loads(serialized_data)

        # Close connection
        conn.close()
    else:
        print("ERROR : verilog_modules.db does not exist")

def clear_verilog_modules():
    """
    deletes the verilog_modules.db file as well as clearing the global verilog_modules list
    """
    global verilog_modules

    if os.path.exists("verilog_modules.db"):
        print(f"INFO : removing verilog_modules.db ...")

        os.remove("verilog_modules.db")
        verilog_modules = []

# example script...
if __name__ == "__main__":

    start_time = time.time()

    default_module = "" # optional: change the default to a module you'll report on often

    parser = argparse.ArgumentParser(
        formatter_class = CustomHelpFormatter,
        description = example_script_help_text
    )
    parser.add_argument("-f", "--file",         dest = "file",          type = str,  nargs = "*",                           help = "filepath to a Verilog file(s) to run script on")
    parser.add_argument("-F", "--filelist",     dest = "filelist",      type = str,  nargs = "?",                           help = "filepath to a list of Verilog file(s) to run script on")
    parser.add_argument("-m", "--module",       dest = "module",        type = str,  nargs = "?", default = default_module, help = "module to analyze and generate reports on")
    parser.add_argument("-r", "--report_hier",  dest = "report_hier",   type = str,  nargs = "?", default = default_module, help = "module to search for \'-m\' defined module under")
    parser.add_argument("-M", "--max_depth",    dest = "max_depth",     type = int,  nargs = "?", default = 0,              help = "number of levels of hierarchy you want to analyze (0 means no limit)")
    parser.add_argument("-u", "--print_unused", dest = "print_unused",  action='store_true',                                help = "generate list of unused modules that were read in")
    parser.add_argument("-d", "--debug_mode",   dest = "debug_mode",    action='store_true',                                help = "enable printing of non-essential debug messages, recommend running only on single file")

    args            = parser.parse_args()
    verilog_file    = args.file
    filelist        = str(args.filelist)
    analyze_module  = str(args.module)
    top_module      = str(args.report_hier)
    max_depth       = int(args.max_depth)
    print_unused    = args.print_unused
    debug_mode      = args.debug_mode

    # if reading in verilog files at start of script, delete the existing verilog modules first...
    if ((verilog_file != [] and str(verilog_file) != "None") or (filelist != "None")):
        clear_verilog_modules()

    # example of reading in verilog files by passing in individual filepaths
    if verilog_file != [] and str(verilog_file) != "None":
        for file in verilog_file:
            parse_verilog(file)

    # example of reading in verilog files by passing in filepath to a filelist
    if filelist != "None":
        parse_file_list(filelist)

    # example of reading in an existing database when no files passed in
    # also good idea to read back `define variables when reading in files
    if ((verilog_file == [] or str(verilog_file) == "None") and (filelist == "None")):
        print(f"INFO : no file specified, using database method...")
        retrieve_verilog_modules()
    else:
        save_verilog_modules()
        report_multi_defined()
        if debug_mode:
            print(f"INFO : verilog_define_variables = {verilog_define_variables}")

    # example of generating a report for a certain module
    if analyze_module != "":
        if verilog_modules == []:
            print(f"INFO : verilog_modules is empty list, skipping reporting stage as this will just cause errors...")
        else:
            report_on_module(analyze_module)
            report_hierarchy(analyze_module, report_unused=print_unused, max_depth=max_depth)

            if print_unused and filelist != "None":
                generate_minimized_filelist(filelist)

            if top_module != "":
                top_module_defined = False
                analyze_module_defined = False
                for modules in verilog_modules:
                    if top_module == modules.name:
                        top_module_defined = True
                    if analyze_module == modules.name:
                        analyze_module_defined = True

                if top_module_defined and analyze_module_defined:
                    out_file = open(f"{analyze_module}_under_{top_module}.txt", 'w')
                    find_all_instances(analyze_module, top_module, out_file)
                    # find_all_instances_re(analyze_module, top_module, out_file)
                    # find_all_instances_iname_re(analyze_module, top_module, out_file)
                    out_file.close()
                    if not readback_instance_paths(f"{analyze_module}_under_{top_module}.txt"):
                        print(f"{color.YELLOW}WARNING{color.RESET} : No instances of {analyze_module} found under {top_module}")
                        print(f"          Removing file {analyze_module}_under_{top_module}.txt as it is blank ...")
                        os.remove(f"{analyze_module}_under_{top_module}.txt")
                else:
                    print(f"{color.RED}ERROR{color.RESET} : module specified in -m and/or -r option not defined")
                    print(f"\tError info: {analyze_module} exists? {str(analyze_module_defined)}")
                    print(f"\tError info: {top_module} exists? {str(top_module_defined)}")
    else:
        print(f"INFO : no module selected for heirarchy reporting.")

    end_time = time.time()

    print(f"INFO : Execution time = {end_time - start_time} seconds")
    if end_time - start_time > 60:
        print(f"       ({math.floor((end_time - start_time) / 60)} minutes)")
