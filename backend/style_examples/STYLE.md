# Student coding style (used for every generated or corrected program)

Rules extracted from the student's own programs in this folder. The AI must write
new code in exactly this style. Add/remove example .ASM files here to change the style;
no code change needed (restart the backend).

- Everything lowercase: directives, instructions, registers, labels (`dosseg`, `.model small`, `mov ax,@data`).
- No indentation at all. No space after commas (`mov dx,offset msg`).
- Program skeleton:
  dosseg / .model small / .data / (variables) / .code / main: / mov ax,@data / mov ds,ax / ... / mov ah,4ch / int 21h / end main
- Entry label `main:` (no `main proc` / `main endp`). Always finish with `end main`.
- Strings: `msg db "text",10,13,"$"` (or `msg1`, `msg2`, ... ; `"text $"` for prompts on the same line).
- Variables: short names, `db ?` for uninitialised bytes (`num db ?`).
- Print a string: `mov ah,9` / `mov dx,offset msg` / `int 21h`. Read a char: `mov ah,1` / `int 21h`.
  Print a char: `mov ah,2` / `mov dl,...` / `int 21h`. Digits: `sub al,30h` / `add dl,30h`.
- One blank line between logical blocks.
- Short labels on their own line: `ag:`, `ex:`, `L:`, `Exit:`.
- No `.stack` line, EXCEPT add `.stack 100h` after `.model small` when the program uses
  push, pop, call or procedures (needed for a correct stack).
- No comments.
