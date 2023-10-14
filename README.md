# ovagen

## Description

* Take source ova file.
* Unpack and prompts client for each OVF properties. i.e we set all values to required one.
* Set Virtual hardware version that we need. i.e vmx-10, vmx-11 etc.
* Recompute all hash value for all files and pack back everything as final ova.

## Usage

python ovagen.py --vmx_types 10,11,12,13,14,15
```