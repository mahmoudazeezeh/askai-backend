dosseg
.model small
.data
msg1 db "enter chatacter",10,13,"$"
msg2 db "output:",10,13,"$"
.code
main:
mov ax,@data
mov ds,ax
mov ah,9
mov dx,offset msg1
int 21h

mov ah,1
int 21h
mov ah,9
mov dx,offset msg2
int 21h
mov ah,2
mov dl,al
int 21h

mov ah,4ch
int 21h
end
