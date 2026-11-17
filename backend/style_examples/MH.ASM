dosseg
.model small
.data
msg db "mahmoud azeezeh top",10,13,"$"
.code
main:
mov ax,@data
mov ds,ax

mov ah,9
mov dx,offset msg
int 21h
mov ah,4ch
int 21h
end
