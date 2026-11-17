dosseg
.model small
.data
msg1 db "enter number $"
msg2 db "enter char $"
msg3 db "result $"
num db ?
character db ?
.code
main:
mov ax,@data
mov ds,ax
mov ah,9
mov dx,offset msg1
int 21h
mov ah,1
int 21h
sub al,30h
mov num,al
mov ah,9
mov dx,offset msg2

int 21h
mov ah,1
int 21h
mov character,al
mov ah,9
mov dx,offset msg3
int 21h
mov cl,num
mov ch,0
mov dl,character
L:
cmp cx,0
jz Exit
mov ah,2
int 21h
dec cx
jmp L

Exit:
mov ah,4ch
int 21h
end main
