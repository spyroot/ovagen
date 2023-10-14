"""
This app respects an OVA file by prompting the user for values
and regenerating new ova file from source ova.

python ovagen.py --vmx_types 10,11,12,13,14,15

Will add support vmx 10,..15

  <ovf:System>
    <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>
    <vssd:InstanceID>0</vssd:InstanceID>
    <vssd:VirtualSystemType>vmx-10 vmx-11 vmx-12 vmx-13 vmx-14 vmx-15</vssd:VirtualSystemType>
  </ovf:System>

 add ovf:value

<ovf:Property ovf:key="org" ovf:qualifiers="MaxLen(32)" ovf:type="string" ovf:userConfigurable="true" ovf:value="">
<ovf:Label>Organization</ovf:Label>
<ovf:Description>Organization Name</ovf:Description>
</ovf:Property>

Author: Mustafa Baramov
mbayramov@vmware.com

"""
import argparse
import json
import shutil
import xml.etree.ElementTree as ET
import os
import tarfile
import hashlib
from typing import List, Optional


def remove_namespace_prefix(text):
    return text.split('}')[1]


def find_product_section(
        namespace: str,
        xml_root: ET.Element):
    """Finds a product section in the given XML tree.
    :param namespace: a namespace that we're looking for
    :param xml_root: root of ET.Element
    :return:
    """
    attr_name = f'.//{{{namespace}}}ProductSection'
    for pd_section in xml_root.findall(attr_name):
        return pd_section
    return None


def property_to_json(property_elem):
    """Take all ova property and serialize to json
    :param property_elem:
    :return:
    """
    property_dict = {}
    for key, value in property_elem.attrib.items():
        key = remove_namespace_prefix(key)
        # add ovf:
        if key.startswith('ovf:'):
            property_dict[key] = value
        else:
            # If the key doesn't start with 'ovf:',
            # add it with the 'ovf:' prefix
            property_dict['ovf:' + key] = value

    label_elem = property_elem.find(
        '{http://schemas.dmtf.org/ovf/envelope/1}Label')
    description_elem = property_elem.find(
        '{http://schemas.dmtf.org/ovf/envelope/1}Description')

    if label_elem is not None:
        property_dict['Label'] = list(label_elem.itertext())[0]
    if description_elem is not None:
        property_dict['Description'] = list(description_elem.itertext())[0]

    return property_dict


def properties_to_json(
        namespace: str,
        product_tree: ET.Element
):
    """take all ovf properties and serialize to json. So we cna display and prompt user
    without any xml walk.
    :param product_tree: a product tree or some xml tree
    :return:
    """
    properties_list = []
    property_elem_query = f'.//{{{namespace}}}Property'
    for property_elem in product_tree.findall(property_elem_query):
        property_json = property_to_json(property_elem)
        properties_list.append(property_json)
    return properties_list


def update_ovf_with_user_values(
        xml_root: ET.Element,
        user_values,
        output_file: str
):
    """Update the given OVF XML tree with the given user values.
    :param xml_root: a root of xml document
    :param user_values: a dict of user values.  Each should have ovf:value , ovf:key etc
    :param output_file: the path to output file.
    :return:
    """
    for prop in xml_root.findall('.//{http://schemas.dmtf.org/ovf/envelope/1}Property'):
        ovf_key = prop.get('ovf:key')
        label_elem = prop.find('{http://schemas.dmtf.org/ovf/envelope/1}Label')

        if ovf_key in user_values and label_elem is not None:
            label_elem.text = user_values[ovf_key]

    tree = ET.ElementTree(xml_root)
    ET.register_namespace(
        'ovf', 'http://schemas.dmtf.org/ovf/envelope/1')
    ET.register_namespace(
        'vmw', 'http://www.vmware.com/schema/ovf')
    ET.register_namespace(
        'rasd', 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData')
    ET.register_namespace(
        'vssd', 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData')
    tree.write(output_file, encoding="utf-8", xml_declaration=True)


def prompt_user_for_values(
        properties_json
):
    """Prompt the user for each OVF property values for the given properties.
    Note it prompt only for the one ovf:userConfigurable="true"

    * ovf:key, indicating what type of configuration is described

    * ovf:type, indicating the format of this information (string,
    boolean, etc.)

    * ovf:qualifiers, indicating any format restrictions (such as string
    minimum or maximum length)

    * ovf:value, containing the actual configuration information (such as
    a string, an IP address, etc.)

    * ovf:userConfigurable, indicating whether the property is meant to be
    edited by the user (through a tool such as the VMware vSphere
    client) before deploying the VM, or whether it should be passed
    through un-edited.

    :param properties_json:  a list of properties
    :return:
    """
    user_values = {}

    for prop in properties_json:
        label = prop.get('Label')
        description = prop.get('Description')
        user_configurable = prop.get('ovf:userConfigurable')
        prop_type = prop.get('ovf:type')

        if user_configurable == 'true':
            if prop_type == 'string':
                print(description)
                value = input(f"Enter value for '{label}': ")
                prop['ovf:value'] = value
                user_values[label] = value
            elif prop_type == 'boolean':
                print(description)
                while True:
                    value = input(f"Enter value for '{label}' (True/False): ").strip().lower()
                    if value in ['true', 'false', '']:
                        if value == '':
                            value = 'true'
                        prop['ovf:value'] = value
                        user_values[label] = value
                        break
                    else:
                        print("Invalid input. Please enter 'True' or 'False'.")

    return user_values


def extract_ova(
        src_dir: str
):
    """Extracts the OVA archive in the given source directory.
    It keeps it flat so don't put more than one ova file in the directory.
    :param src_dir:
    :return:
    """
    ova_file = None
    for filename in os.listdir(src_dir):
        if filename.endswith(".ova"):
            ova_file = os.path.join(src_dir, filename)
            break

    if ova_file is None:
        raise FileNotFoundError(
            "No OVA file found in the source directory.")

    try:
        with tarfile.open(ova_file, "r") as ova_tar:
            ova_tar.extractall(path=src_dir)
    except Exception as e:
        raise RuntimeError(f"Failed to extract OVA archive: {str(e)}")

    return src_dir


def copy_files(
        src_dir: str,
        dst_dir: str
):
    """
    Copy all files from src_dir to dst_dir,
    skipping files with the ".ova" extension.

    :param src_dir: Source directory
    :param dst_dir: Destination directory
    """
    for filename in os.listdir(src_dir):
        if filename.endswith(".ova"):
            continue  # Skip files with ".ova" extension
        src_file = os.path.join(src_dir, filename)
        dst_file = os.path.join(dst_dir, filename)
        if os.path.isfile(src_file):
            shutil.copy(src_file, dst_file)


def find_file_in_subdirectories(
        base_dir: str,
        file_extension="ovf"
):
    """
    Find and return the full path of the first ".ovf"
    file found in subdirectories of the given base directory.

    :param file_extension:
    :param base_dir: The base directory to search in
    :return: Full path of the first ".ovf" file found, or None if not found
    """
    for root, _, files in os.walk(base_dir):
        for filename in files:
            if filename.endswith(f".{file_extension}"):
                return os.path.join(root, filename)
    return None


def create_tar_archive(dst_dir, output_tar_file):
    """
    Create a TAR archive containing all files in the destination directory.

    :param dst_dir: Path to the destination directory
    :param output_tar_file: Path to the output TAR file
    """
    with tarfile.open(output_tar_file, "w") as tar:
        for root, _, files in os.walk(dst_dir):
            for file in files:
                file_path = os.path.join(root, file)
                tar.add(file_path, arcname=os.path.relpath(file_path, dst_dir))


def generate_new_ovf(
        xml_root: ET.Element,
        file_path: str):
    """Regenerate new ovf file based on user input
    :return:
    """
    namespaces = {
        'ovf': 'http://schemas.dmtf.org/ovf/envelope/1',
        'vmw': 'http://www.vmware.com/schema/ovf',
        'rasd': 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData',
        'vssd': 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData'
    }
    product_section = find_product_section(namespaces['ovf'], xml_root)
    properties_json = properties_to_json(namespaces['ovf'], product_section)
    user_values = prompt_user_for_values(properties_json)

    modified_json_str = json.dumps(properties_json, indent=4)
    print("Modified JSON:")
    print(modified_json_str)

    # update ovf and save
    update_ovf_with_user_values(xml_root, user_values, file_path)


def update_sha1_values(
        mf_file_path: str,
        base_dir: str):
    """
    Update SHA1 values in the .mf file based
    on the files in the specified base directory.

    :param mf_file_path: Path to the .mf file to be updated
    :param base_dir: The base directory containing the files
    """
    # Create a dictionary to store the SHA1 values
    sha1_values = {}
    for root, _, files in os.walk(base_dir):
        for filename in files:
            file_path = os.path.join(root, filename)
            with open(file_path, 'rb') as f:
                file_data = f.read()
            sha1_hash = hashlib.sha1(file_data).hexdigest()
            sha1_values[os.path.relpath(file_path, base_dir)] = sha1_hash

    # Update the .mf file with the new SHA1 values
    with open(mf_file_path, 'r') as mf_file:
        mf_lines = mf_file.readlines()

    for i, line in enumerate(mf_lines):
        if line.strip().startswith("SHA1("):
            file_info = line.strip().split('= ')
            file_name = file_info[0].replace("SHA1(", "").replace(")", "")
            if file_name in sha1_values:
                mf_lines[i] = f"SHA1({file_name})= {sha1_values[file_name]}\n"

    # Write the updated .mf file
    with open(mf_file_path, 'w') as mf_file:
        mf_file.writelines(mf_lines)


def system_section(
        xml_root: ET.Element,
        namespace: Optional[str] = "http://schemas.dmtf.org/ovf/envelope/1"
):
    return xml_root.find(f'.//{{{namespace}}}System')


def update_system_section(
        xml_root: ET.Element,
        vmx_types: List[int],
        namespace: Optional[str] = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"):
    """
    :param namespace:
    :param xml_root:
    :param vmx_types: i.e. vmx-10 vmx-11 vmx-13 list of int for each type we want to support
    :return:
    """
    system_elem = system_section(xml_root)
    if system_elem is not None:
        element_name_elem = system_elem.find(
            f'{{{namespace}}}ElementName')
        virtual_system_type_elem = system_elem.find(
            f'{{{namespace}}}VirtualSystemType')

        if element_name_elem is not None and virtual_system_type_elem is not None:
            if virtual_system_type_elem is not None:
                virtual_system_type_text = " ".join([f"vmx-{vmx_type}" for vmx_type in vmx_types])
                virtual_system_type_elem.text = virtual_system_type_text

        return xml_root


def main(cmd):
    """
    :return:
    """

    # extra OVA file
    print(f"Extracting ova from: {cmd.src}")
    extract_ova(cmd.src)
    os.makedirs(cmd.dst, exist_ok=True)
    copy_files(cmd.src, cmd.dst)
    print(f"Copied ova content to: {cmd.dst}")

    new_ovf = find_file_in_subdirectories(cmd.dst, file_extension="ovf")
    tree = ET.parse(new_ovf)
    xml_root = tree.getroot()

    # update system section if require
    if cmd.vmx_types:
        update_system_section(xml_root, cmd.vmx_types)

    # respec ova by prompting for each ova property
    # and regenerating ovf
    ovf_file = find_file_in_subdirectories(cmd.dst)
    print(f"Found ovf file in: {ovf_file}")
    generate_new_ovf(xml_root, ovf_file)

    # after we update ovf we, recompute sha1
    mf_file = find_file_in_subdirectories(cmd.dst, file_extension="mf")
    update_sha1_values(mf_file, cmd.dst)
    # create new ova.
    create_tar_archive(cmd.dst, cmd.file_name)


if __name__ == '__main__':
    """
    """
    parser = argparse.ArgumentParser(description="Process OVA files")
    parser.add_argument("--src", help="Source directory containing the .ova file", type=str, default="src")
    parser.add_argument("--dst", help="Destination directory", type=str, default="dst")
    parser.add_argument("--file_name", help="output file name.", type=str, default="output.ova")
    parser.add_argument("--vmx_types", help="List of VMX types to update VirtualSystemType (comma-separated)", type=str)
    args = parser.parse_args()

    if args.vmx_types:
        args.vmx_types = [int(x) for x in args.vmx_types.split(',')]

    main(args)
