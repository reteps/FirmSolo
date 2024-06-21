import os, sys
currentdir = os.path.dirname(os.path.realpath(__file__))
parentdir = os.path.dirname(currentdir)
sys.path.append(parentdir)
import custom_utils as cu
import stage1.get_symbol_info as gsi
import subprocess
import traceback
import json
import re


sym_template = """
int %(SYM_NAME)s(void)
{
    return 0;   
}
EXPORT_SYMBOL(%(SYM_NAME)s);
"""
class Symbols():
    def __init__(self, info):
        self.info = info
    
    def add_template(self, syms, kern_dir):
        kern_init_main_fl = "{}/init/main.c".format(kern_dir)
        with open(kern_init_main_fl, "r") as f:
            lines = f.readlines()
        
        template = ""
        print("UNKNOWN SYMS", len(syms), syms)
        for sym in syms:
            if "__tracepoint" in sym:
                continue
            if "per_cpu__" in sym:
                continue
            if "dma_cache_inv" in sym:
                continue
            if "__aeabi" in sym:
                continue
            if "per_cpu__xt_info_locks" in sym:
                continue
            if "__kstrtab" in sym:
                continue
            if "__ksymtab_" in sym:
                continue

            template += "\n" + sym_template % dict(SYM_NAME = sym)
        
        template_split = template.split("\n")

        template = list(map(lambda x:x+"\n", template_split))
        
        # Open the main.c file and add the dummy templates for all the
        # symbols that do not exist in the kernel source code
        for i, line in enumerate(lines):
            if "char * envp_init[MAX_INIT_ENVS+2]" in line or "char *envp_init[MAX_INIT_ENVS+2]" in line:
                index = i - 2
                break
        #for indx, line in enumerate(lines):
            #if "unsigned int fdyne_execute;" in line:
                #index = indx - 1
                #break
                
        for ln in template:
            lines.insert(index, ln)
            index += 1
        
        with open(kern_init_main_fl, "w") as f:
            f.writelines(lines)

    def make_global(self, files, symbol, kern_dir):
        outcome = []
        for file in files:
            if file == "" or file == "\n":
                continue
            fl = file.split()[0]
            
            # Find the information about the symbol, where it is defined so that we change the static definition to global
            cmd = "ctags --fields=+ne --output-format=json -o - --sort=no {}/{} |grep {}".format(kern_dir, fl, symbol)
            results = []
            try:
                res = subprocess.check_output(cmd, shell=True).decode("utf-8")
                results = res.split("\n")
                # for result in results:
                #     outputs.append(json.loads(result))
            except:
                pass
                # print(traceback.format_exc())
                # print("CMD", cmd, "\n")
            
            if results:
                for output in results:
                    outcome.append(output)
                #print("Start", start, "End", end, "Type", type, "Kind", kind, "Symbol", symbol, "File", fl)
        
        return outcome

    def modify_symbol(self, json_dict, kernel):
        print('In modify symbol')
        name = json_dict['name']
        print("Name", name)
        path = json_dict['path']
        print("Path", path)
        pattern = json_dict['pattern']
        start = json_dict['line']
        end = json_dict['end']
        
        actual_path = "{}{}".format(cu.kern_dir, path.split(f"kernel_sources//{kernel}")[1])
        extension = actual_path.split(".")[-1]
        if extension != "c":
            return
        
        prototype = str(pattern).strip("/^$")
        print(json_dict, actual_path, start, end)
        
        # This must be a ctags bug for an anonymous struct member
        if "__anona" in name:
            return
        if "extern" in prototype or "#define" in prototype or "__read_mostly" in prototype:
            return
        # Not a definition?
        if "(" not in prototype and "=" not in prototype and "{" not in prototype:
            return

        if "static " in prototype:
            what_to_replace = "static "
            prototype = prototype.replace("static ", "")
        elif "inline " in prototype:
            what_to_replace = "inline "
            prototype = prototype.replace("inline ", "")
        else:
            what_to_replace = ""

        ### We want to change static types to global types
        with open(actual_path, "r") as f:
            lines = f.readlines()
        
        indx = start - 1
        print(lines[indx])
        for line in lines[start-1:]:
            if prototype in line:
                break
            indx += 1
        
        length = int(end) - int(start)
        for line in lines[indx + length + 1: len(lines)+1]:
            res = re.search(f"EXPORT_.+({name})", line)
            if res:
                return
        lines[indx] = lines[indx].replace(what_to_replace, "")
        lines.insert(indx + length + 1, "EXPORT_SYMBOL({});\n".format(name))
        
        found_module_header = False
        for i, line in enumerate(lines):
            if "#include" in line:
                while "#include" in line:
                    line = lines[i]
                    if "linux/module.h" in line:
                        found_module_header = True
                        break
                    i+=1
                if found_module_header:
                    break
                else:
                    lines.insert(i-1, "#include <linux/module.h>")
                    break


        with open(actual_path, "w") as f:
            f.writelines(lines)

        if name not in self.info['static_syms_changed']:
            self.info['static_syms_changed'][name] = set()
        self.info['static_syms_changed'][name].add(actual_path)

            
    def add_global_to_kernel(self, static_info, kernel):
        self.info['static_syms_changed'] = {}
        for meta in static_info:
            for data in meta:
                if not data:
                    continue
                try:
                    json_dict = json.loads(data)
                    self.modify_symbol(json_dict, kernel)
                except:
                    print(traceback.format_exc())


def read_sym_dictionary(kernel,arch):
    kernel_dict_file = "{}/{}/{}_{}_sym_dict.pkl".format(cu.kern_dicts,
                                                            kernel,
                                                            kernel, arch)
    try:
        kern_dict = cu.read_pickle(kernel_dict_file)
    except:
        kern_dict = {}

    return kern_dict

# Find all the symbols that do exist in the kernel source
# code and add a dummy template for them in the main.c
# This will be called from firm_kern_comp.py
def fix_unknown_syms(image, kern_dir):
    print("KERN DIR PATH", cu.kern_dir)
    info = cu.get_image_info(image, "all")
    
    kernel = cu.kernel_prefix + info['kernel']
    sym_dict = read_sym_dictionary(kernel, info['arch'])
    kern_source = "{}/{}".format(cu.kern_sources, kernel)
    
    syms_obj = Symbols(info)

    if "static_syms" not in info.keys():
        syms_obj.info['static_syms'] = []
        syms_obj.info['not_exist_mod_syms'] = set()    

        for sym in syms_obj.info['unknown_mod_syms']:
            if sym_dict[sym] == '' or sym_dict[sym] == None:
                fl = gsi.find_definition([sym, {}, kern_source])
                if fl != '':
                    filez = fl.split("\n")
                    outcome = syms_obj.make_global(filez, sym, kern_source)
                    syms_obj.info['static_syms'].append(outcome)
                else:
                    syms_obj.info['not_exist_mod_syms'].add(sym)
            else:
                filez = sym_dict[sym].split("\n")
                export_found = False
                for file in filez:
                    if "EXPORT" in file:
                        export_found = True
                        break
                if not export_found:
                    outcome = syms_obj.make_global(filez, sym, kern_source)
                    syms_obj.info['static_syms'].append(outcome)
                continue
    
    #syms_obj.add_global_to_kernel(info['static_syms'], kernel)
    
    syms_obj.add_template(syms_obj.info['not_exist_mod_syms'], kern_dir)
    
    info_fl = "{}/{}.pkl".format(cu.img_info_path, image)
    cu.write_pickle(info_fl, syms_obj.info)
